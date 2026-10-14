"""OpenAI-compatible adapter that lets Microsoft-Decision-1 drive a Copilot SDK agent loop.

Decision-1 is not a generative model: it answers typed questions (choice / noul / score).
The Copilot runtime talks to this adapter as if it were a chat model. For every request the
adapter sends Decision-1 the same prompt text and latest tool result the LLM agent sees, asks it to
`choice` between the same options, and replies with the selected tool call. It contains no game
logic (no strategy, no forced moves, no backtracking memory): that all lives in game.py and is shared.
"""
from __future__ import annotations

import json
import time
import uuid

import aiohttp
from aiohttp import web

import asyncio

import auth
import config
from prompts import system_prompt, task_prompt

_session: aiohttp.ClientSession | None = None
REGISTRY: dict[str, "Policy"] = {}


class Policy:
    """Per-game state for the Decision-1 agent."""

    def __init__(self, opts: dict) -> None:
        self.opts = opts
        self.instructions = system_prompt(opts) + "\n\n" + task_prompt(opts)
        self.calls = 0
        self.skipped = 0  # single-option steps answered without a model call (Decision-1 needs >= 2 options)
        self.total_ms = 0.0


def register(token: str, opts: dict) -> Policy:
    REGISTRY[token] = Policy(opts)
    return REGISTRY[token]


async def _decision(state, question_id: str, instructions: str, criteria: dict) -> dict:
    global _session
    if _session is None:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    tok = auth.token() if auth.fresh() else await asyncio.to_thread(auth.token)
    body = {
        "model": config.DECISION_DEPLOYMENT,
        "state": state,
        "questions": {question_id: {"type": "choice", "instructions": instructions, "criteria": criteria}},
    }
    url = f"{config.FOUNDRY_HOST}/providers/microsoft/v1/systemone"
    for attempt in range(4):
        async with _session.post(url, json=body, headers={"Authorization": f"Bearer {tok}"}) as r:
            if r.status == 429 or r.status >= 500:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return (await r.json())["answers"][question_id]
    raise RuntimeError("Decision-1 API unavailable")


def _last_tool_content(messages: list[dict]):
    for m in reversed(messages):
        if m.get("role") == "tool":
            c = m.get("content")
            if isinstance(c, list):
                c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c
    return None


def _pick(answer: dict, allowed: list[str]) -> str:
    probs = answer.get("probabilities", {})
    return max(allowed, key=lambda k: probs.get(k, 0))


async def _ask(policy: Policy, state: dict, question_id: str, criteria: dict) -> str:
    t0 = time.perf_counter()
    ans = await _decision(state, question_id, "Choose the next action.", criteria)
    policy.calls += 1
    policy.total_ms += (time.perf_counter() - t0) * 1000
    return _pick(ans, list(criteria))


async def decide(policy: Policy, messages: list[dict]):
    """Returns ("tool", name, args) or ("text", message).

    Fairness contract: this adapter adds no game logic. Every step is one Decision-1 call whose
    `state` is the same text and the same tool-result JSON the LLM agent receives, and whose options
    are exactly the moves the LLM agent is offered (`candidate_moves`, or `undo` when stuck).
    """
    raw = _last_tool_content(messages)
    state = {"instructions": policy.instructions}
    if raw is None:
        crit = {f"{r},{c}": f"move(row={r}, col={c})" for r in range(10) for c in range(10)}
        choice = await _ask(policy, state, "next_action", crit)
        r, c = map(int, choice.split(","))
        return ("tool", "move", {"row": r, "col": c})

    try:
        res = json.loads(raw)
    except Exception:
        return ("text", f"Could not read the game state: {str(raw)[:200]}")
    if res.get("solved"):
        return ("text", "The board is completely filled: 1 to 100. Solved!")

    state["latest_tool_result"] = res
    crit = {}
    for m in res.get("candidate_moves", []):
        desc = f"move(row={m['move'][0]}, col={m['move'][1]})"
        if "onward_moves" in m:
            desc += f"; onward_moves={m['onward_moves']}"
        crit[f"{m['move'][0]},{m['move'][1]}"] = desc
    if not policy.opts["auto_forced"] and res.get("filled", 0) > 0:
        crit["undo"] = "undo(): remove the last number to backtrack"
    if len(crit) < 2:  # Decision-1 needs >= 2 options: a single possible action is played without a call
        policy.skipped += 1
        only = next(iter(crit), "undo")
        if only == "undo":
            return ("tool", "undo", {})
        r, c = map(int, only.split(","))
        return ("tool", "move", {"row": r, "col": c})
    choice = await _ask(policy, state, "next_action", crit)
    if choice == "undo":
        return ("tool", "undo", {})
    r, c = map(int, choice.split(","))
    return ("tool", "move", {"row": r, "col": c})


def _chunk(cid: str, model: str, delta: dict, finish=None, usage=None) -> str:
    obj = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        obj["usage"] = usage
        obj["choices"] = []
    return f"data: {json.dumps(obj)}\n\n"


async def chat_completions(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    policy = REGISTRY.get(token)
    if policy is None:
        return web.json_response({"error": {"message": "unknown game token"}}, status=401)

    try:
        decision = await decide(policy, body.get("messages", []))
    except Exception as exc:  # surface as a model error so the harness records it
        return web.json_response({"error": {"message": f"Decision-1 adapter error: {exc}"}}, status=500)

    model = body.get("model", "decision-1")
    cid = "chatcmpl-" + uuid.uuid4().hex[:24]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if decision[0] == "tool":
        _, name, args = decision
        call = {"id": "call_" + uuid.uuid4().hex[:20], "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}
        message = {"role": "assistant", "content": None, "tool_calls": [call]}
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": decision[1]}
        finish = "stop"

    if not body.get("stream"):
        return web.json_response({"id": cid, "object": "chat.completion", "created": int(time.time()),
                                  "model": model, "usage": usage,
                                  "choices": [{"index": 0, "message": message, "finish_reason": finish}]})

    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    await resp.write(_chunk(cid, model, {"role": "assistant"}).encode())
    if decision[0] == "tool":
        c = message["tool_calls"][0]
        await resp.write(_chunk(cid, model, {"tool_calls": [{"index": 0, "id": c["id"], "type": "function",
                                                              "function": {"name": name, "arguments": ""}}]}).encode())
        await resp.write(_chunk(cid, model, {"tool_calls": [{"index": 0,
                                                              "function": {"arguments": c["function"]["arguments"]}}]}).encode())
    else:
        await resp.write(_chunk(cid, model, {"content": message["content"]}).encode())
    await resp.write(_chunk(cid, model, {}, finish=finish).encode())
    if (body.get("stream_options") or {}).get("include_usage"):
        await resp.write(_chunk(cid, model, {}, usage=usage).encode())
    await resp.write(b"data: [DONE]\n\n")
    await resp.write_eof()
    return resp
