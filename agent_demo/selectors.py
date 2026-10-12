"""Two ways to choose the next tool: a native-tool-calling LLM, or Decision-1 (+ a small LLM for arguments)."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from agent_demo.clients import decision_client, openai_client
from agent_demo.tools import TOOLS
from decision_client import choice

def load_pricing() -> dict:
    return json.loads((Path(__file__).parent / "pricing.json").read_text())["per_1m_tokens"]

SYSTEM = (
    "You are an operations assistant. Complete the user's task by calling one tool at a time. "
    "Do not repeat a call that already succeeded. When everything the task asks for is done, call finish with a short final answer."
)

NEXT_TOOL_QUESTION = (
    "You plan the next step of an operations assistant. Given the task and the steps already done, "
    "which tool should be called next? Choose finish only when everything the task asks for is done. "
    "Do not repeat a step that already succeeded."
)


@dataclass
class Call:
    phase: str  # "select" or "args"
    model: str
    ms: float
    input_tokens: int
    output_tokens: int
    cost: float | None
    output: object = None  # raw model output shown in the UI


def _summarize_output(resp) -> list[dict]:
    out = []
    for o in resp.output:
        if o.type == "function_call":
            out.append({"function_call": o.name, "arguments": json.loads(o.arguments)})
        elif o.type == "message":
            out.append({"message": resp.output_text})
        else:
            out.append({"type": o.type})
    return out

@dataclass
class Selection:
    tool: str
    args: dict
    calls: list[Call]
    confidence: float | None = None
    probs: dict[str, float] = field(default_factory=dict)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    p = load_pricing().get(model) or {}
    if p.get("input") is None or p.get("output") is None:
        return None
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def _tool_schema(name: str) -> dict:
    t = TOOLS[name]
    return {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}


def _response_input(task: str, history: list[dict]) -> list[dict]:
    items: list[dict] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    for i, h in enumerate(history):
        cid = f"call_{i}"
        items.append({"type": "function_call", "call_id": cid, "name": h["tool"], "arguments": json.dumps(h["args"])})
        items.append({"type": "function_call_output", "call_id": cid, "output": h["result"]})
    return items


class LLMSelector:
    """The LLM chooses the tool and its arguments in one native tool-calling request."""

    def __init__(self, deployment: str | None = None) -> None:
        self.client = openai_client()
        self.model = deployment or os.environ.get("LLM_DEPLOYMENT", "gpt-6.1-sol")
        # gpt-6.x function tools need the Responses API with a reasoning effort.
        self.reasoning_effort = os.environ.get("LLM_REASONING_EFFORT", "low")

    def select(self, task: str, history: list[dict]) -> Selection:
        start = perf_counter()
        resp = self.client.responses.create(
            model=self.model,
            input=_response_input(task, history),
            tools=[{"type": "function", **_tool_schema(n)["function"]} for n in TOOLS],
            tool_choice="required",
            parallel_tool_calls=False,
            reasoning={"effort": self.reasoning_effort},
        )
        ms = (perf_counter() - start) * 1000
        call = next((o for o in resp.output if o.type == "function_call"), None)
        tool, args = (call.name, json.loads(call.arguments)) if call else ("finish", {"answer": resp.output_text})
        u = resp.usage
        return Selection(tool, args, [Call("select", self.model, ms, u.input_tokens, u.output_tokens, cost_usd(self.model, u.input_tokens, u.output_tokens), _summarize_output(resp))])


class DecisionSelector:
    """Decision-1 chooses the tool; a small LLM only fills in the chosen tool's arguments."""

    def __init__(self, arg_deployment: str | None = None) -> None:
        self.decision = decision_client()
        self.client = openai_client()
        self.model = self.decision.deployment
        self.arg_model = arg_deployment or os.environ.get("ARG_LLM_DEPLOYMENT", "gpt-6-luna")

    def select(self, task: str, history: list[dict]) -> Selection:
        state = {
            "task": task,
            "steps_done": [{"tool": h["tool"], "args": h["args"], "result": h["result"]} for h in history],
        }
        options = {name: t.description for name, t in TOOLS.items()}
        start = perf_counter()
        result = self.decision.decide(state, {"next_tool": choice(NEXT_TOOL_QUESTION, options)})
        ms = (perf_counter() - start) * 1000
        answer = result["answers"]["next_tool"]
        tool = answer["choice"]
        usage = result["usage"]
        calls = [Call("select", self.model, ms, usage["input_tokens"], usage["output_tokens"], cost_usd(self.model, usage["input_tokens"], usage["output_tokens"]), answer)]

        args = None
        for attempt in range(2):
            start = perf_counter()
            resp = self.client.responses.create(
                model=self.arg_model,
                input=_response_input(task, history),
                tools=[{"type": "function", **_tool_schema(tool)["function"]}],
                tool_choice={"type": "function", "name": tool},
                reasoning={"effort": os.environ.get("ARG_REASONING_EFFORT", "low")},
            )
            ms = (perf_counter() - start) * 1000
            u = resp.usage
            calls.append(Call("args", self.arg_model, ms, u.input_tokens, u.output_tokens, cost_usd(self.arg_model, u.input_tokens, u.output_tokens), _summarize_output(resp)))
            fn = next((o for o in resp.output if o.type == "function_call"), None)
            if fn:
                args = json.loads(fn.arguments)
                break
        if args is None:
            raise RuntimeError(
                f"{self.arg_model} returned no function call for '{tool}' after 2 attempts "
                f"(status={resp.status}, incomplete={resp.incomplete_details}, output types={[o.type for o in resp.output]})"
            )
        return Selection(tool, args, calls, answer.get("confidence"), answer.get("probabilities", {}))
