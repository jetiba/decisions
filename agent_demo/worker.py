"""One agent loop in its own process, so the two loops never share an interpreter, GIL, or connection pool.

Protocol (JSON lines): stdin gets {"task": ...} then "go"; stdout emits events, starting with {"type": "ready"}.
Usage: python -m agent_demo.worker llm|decision
"""

import json
import sys
from time import perf_counter

from agent_demo.clients import warm_up
from agent_demo.loop import run_agent
from agent_demo.selectors import DecisionSelector, LLMSelector


def emit(ev: dict) -> None:
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


def main() -> None:
    side = sys.argv[1]
    task = json.loads(sys.stdin.readline())["task"]
    status, t0 = "error", perf_counter()
    try:
        warm_up(side)
        selector = LLMSelector() if side == "llm" else DecisionSelector()
        emit({"type": "ready"})
        sys.stdin.readline()  # "go": the server releases both loops together
        t0 = perf_counter()
        emit({"type": "start"})
        status = run_agent(selector, task, emit)
    except Exception as exc:
        emit({"type": "error", "message": str(exc)[:500]})
    emit({"type": "done", "status": status, "wall_ms": (perf_counter() - t0) * 1000})


if __name__ == "__main__":
    main()
