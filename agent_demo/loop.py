"""Agent loop shared by both selectors, so only the tool-selection strategy differs."""

from dataclasses import asdict
from time import perf_counter
from typing import Callable

from agent_demo.tools import run_tool

MAX_STEPS = 8


def run_agent(selector, task: str, emit: Callable[[dict], None]) -> str:
    history: list[dict] = []
    for step in range(1, MAX_STEPS + 1):
        emit({"type": "thinking", "step": step})
        sel = selector.select(task, history)
        start = perf_counter()
        result = run_tool(sel.tool, sel.args)
        emit(
            {
                "type": "step",
                "step": step,
                "tool": sel.tool,
                "args": sel.args,
                "result": result,
                "tool_ms": (perf_counter() - start) * 1000,
                "confidence": sel.confidence,
                "probs": sel.probs,
                "calls": [asdict(c) for c in sel.calls],
            }
        )
        if sel.tool == "finish":
            return "finished"
        history.append({"tool": sel.tool, "args": sel.args, "result": result})
    return "max_steps"
