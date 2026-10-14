"""Copilot SDK harness: one agent loop per game, with `move` / `undo` tools."""
import asyncio
import json
import time
import uuid

from pydantic import BaseModel, Field

from copilot import CopilotClient, define_tool
from copilot.session import PermissionHandler
from copilot.session_events import SessionEventType

import auth
import config
import diag
import shim
from game import Game
from options import normalize
from prompts import system_prompt, task_prompt


class MoveParams(BaseModel):
    row: int = Field(description="Row index 0-9 (0 = top)")
    col: int = Field(description="Column index 0-9 (0 = left)")


class NoParams(BaseModel):
    pass


def astra_provider(_token: str) -> dict:
    tok = auth.token()  # cached; run_game calls the provider off the event loop
    return {"type": "azure", "base_url": config.OPENAI_HOST, "bearer_token": tok, "wire_api": "responses"}


def decision_provider(token: str) -> dict:
    return {"type": "openai", "base_url": config.SHIM_BASE_URL, "bearer_token": token, "wire_api": "completions"}


AGENTS = {
    "astra": {"key": "astra", "label": config.DEFAULT_LLM, "model": config.LLMS[config.DEFAULT_LLM], "provider": astra_provider},
    "decision": {"key": "decision", "label": "Microsoft-Decision-1", "model": "decision-1", "provider": decision_provider},
}


def with_llm(key: str, llm: str) -> dict:
    """Agent definition with the chat model swapped; the harness, prompts and tools stay identical."""
    agent = dict(AGENTS[key])
    if key == "astra":
        agent.update(label=llm, model=config.LLMS[llm])
    return agent


def new_client() -> CopilotClient:
    return CopilotClient(mode="empty", base_directory=config.COPILOT_HOME)


STALL_S = 30.0


async def run_game(client: CopilotClient, agent: dict, game_no: int, emit, timeout_s: float,
                   max_tool_calls: int, stop: asyncio.Event, opts: dict | None = None) -> dict:
    opts = normalize(opts)
    game = Game(seed=game_no, opts=opts)
    token = uuid.uuid4().hex
    policy = shim.register(token, opts) if agent["key"] == "decision" else None
    stats = {"tool_calls": 0, "model_calls": 0, "input_tokens": 0, "output_tokens": 0, "stalls": 0, "decision_ms": 0.0, "stall_ms": 0.0, "auto_steps": 0}
    solved_evt, idle_evt, budget_evt = asyncio.Event(), asyncio.Event(), asyncio.Event()
    error: list[str] = []
    last_activity = [time.perf_counter()]
    t0 = time.perf_counter()
    wall0 = time.time()
    elapsed = lambda: round(time.perf_counter() - t0, 2)

    def emit_state(kind: str, **extra):
        emit({"type": kind, "agent": agent["key"], "game": game_no, "filled": game.filled,
              "elapsed": elapsed(), "illegal": game.illegal, "undos": game.undos,
              "tool_calls": stats["tool_calls"], **extra})

    ready_at = [time.perf_counter()]  # when the model was last handed control (prompt sent / tool result returned)

    def count_call():
        now = time.perf_counter()
        stats["decision_ms"] += (now - ready_at[0]) * 1000
        last_activity[0] = now
        stats["tool_calls"] += 1
        if stats["tool_calls"] >= max_tool_calls:
            budget_evt.set()

    def play_forced() -> list[str]:
        """Auto-plays single-option steps (identical for both agents) and reports them to the model."""
        notes = []
        while (step := game.forced_step()) is not None:
            kind, r, c, n = step
            emit_state(kind, r=r, c=c, n=n, auto=True)
            notes.append(f"{kind} ({r},{c})" if kind == "move" else f"undo ({r},{c})")
        return notes

    def result_json(message: str) -> str:
        notes = play_forced()
        if game.solved:
            solved_evt.set()
        if notes:
            stats["auto_steps"] += len(notes)
            message += " Forced steps (only one option) were played automatically: " + ", ".join(notes) + "."
        out = json.dumps(game.tool_result(message=message))
        ready_at[0] = time.perf_counter()
        return out

    @define_tool(name="move", description="Place the next number on the given square (row, col in 0-9).",
                 skip_permission=True)
    async def move(params: MoveParams) -> str:
        count_call()
        err = game.move(params.row, params.col)
        if err:
            emit_state("illegal", message=err)
            ready_at[0] = time.perf_counter()
            return json.dumps(game.tool_result(ok=False, message=err))
        emit_state("move", r=params.row, c=params.col, n=game.filled)
        return result_json(f"Placed {game.filled}.")

    @define_tool(name="undo", description="Remove the most recently placed number to backtrack.",
                 skip_permission=True)
    async def undo(params: NoParams) -> str:
        count_call()
        res = game.undo()
        if res is None:
            ready_at[0] = time.perf_counter()
            return json.dumps(game.tool_result(ok=False, message="Nothing to undo."))
        emit_state("undo", r=res[0], c=res[1], n=res[2])
        return result_json(f"Removed {res[2]}.")

    emit_state("game_start", label=agent["label"])
    status = "error"
    session = None
    try:
        session = await client.create_session(
            on_permission_request=PermissionHandler.approve_all,
            model=agent["model"],
            tools=[move, undo],
            available_tools=["move", "undo"],
            system_message={"mode": "replace", "content": system_prompt(opts)},
            provider=await asyncio.to_thread(agent["provider"], token),
            infinite_sessions={"enabled": False},
        )

        def on_event(ev):
            t = ev.type
            last_activity[0] = time.perf_counter()
            if t == SessionEventType.ASSISTANT_USAGE:
                stats["model_calls"] += 1
                stats["input_tokens"] += ev.data.input_tokens or 0
                stats["output_tokens"] += ev.data.output_tokens or 0
            elif t == SessionEventType.SESSION_ERROR:
                error.append(str(getattr(ev.data, "message", ev.data))[:500])
                idle_evt.set()
            elif t == SessionEventType.SESSION_IDLE:
                idle_evt.set()

        session.on(on_event)
        deadline = t0 + timeout_s
        nudges = 0
        stalls = 0
        ready_at[0] = time.perf_counter()
        await session.send(task_prompt(opts))
        status = "running"
        while status == "running":
            waiters = {asyncio.ensure_future(e.wait()): n for n, e in
                       [("solved", solved_evt), ("idle", idle_evt), ("budget", budget_evt), ("stop", stop)]}
            remaining = deadline - time.perf_counter()
            done, pending = await asyncio.wait(waiters, timeout=max(0.0, min(remaining, STALL_S)),
                                               return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            if not done and remaining > STALL_S:
                # Watchdog: a model request occasionally hangs without any response (transport, not model
                # latency). Abort the stuck turn and resend; the wait is reported as stalls / stall_ms.
                idle_for = time.perf_counter() - last_activity[0]
                if idle_for >= STALL_S and stalls < 20:
                    stalls += 1
                    stats["stalls"] = stalls
                    stats["stall_ms"] += idle_for * 1000
                    try:
                        await asyncio.wait_for(session.abort(), 10)
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(1)
                    idle_evt.clear()
                    last_activity[0] = ready_at[0] = time.perf_counter()
                    await session.send("Continue playing: call move or undo.")
                continue
            reason = next((waiters[d] for d in done), "timeout")
            if reason == "solved":
                status = "solved"
            elif reason == "stop":
                status = "stopped"
            elif reason == "budget":
                status = "budget"
            elif reason == "timeout":
                status = "timeout"
            else:  # idle: the model ended its turn
                if error:
                    status = "error"
                elif nudges < 5:
                    nudges += 1
                    idle_evt.clear()
                    await session.send(f"The puzzle is not solved yet ({game.filled}/100 filled). "
                                       "Keep playing with the tools; use undo if you are stuck.")
                else:
                    status = "gave_up"
    except Exception as exc:  # noqa: BLE001
        error.append(repr(exc)[:500])
        status = "error"
    finally:
        duration = elapsed()
        if session is not None:
            try:
                await asyncio.wait_for(session.abort(), 10)
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(session.disconnect(), 10)
            except Exception:  # noqa: BLE001
                pass

    result = {
        "agent": agent["key"], "label": agent["label"], "game": game_no, "status": status,
        "solved": status == "solved", "duration_s": duration, "filled": game.filled,
        "max_filled": game.max_filled, "moves_made": game.filled + game.undos, "illegal_moves": game.illegal,
        "undos": game.undos, **stats, "error": error[0] if error else None,
        "board": game.grid, "ts": time.time(), "options": opts,
    }
    if policy:  # Decision-1 only: time spent in the Decision-1 endpoint itself (a subset of decision_ms)
        result["model_calls"] = policy.calls
        result["api_ms"] = round(policy.total_ms, 1)
        result["skipped_single_option_steps"] = policy.skipped
    result.update(diag.window(wall0, time.time()))
    result["decision_ms"] = round(stats["decision_ms"], 1)  # the timer restarts after a stall, so hangs are excluded
    result["avg_decision_ms"] = round(result["decision_ms"] / result["tool_calls"], 1) if result["tool_calls"] else None
    result["stall_ms"] = round(stats["stall_ms"], 1)
    result["harness_ms"] = round(max(0.0, duration * 1000 - result["decision_ms"] - result["stall_ms"]), 1)
    shim.REGISTRY.pop(token, None)
    return result
