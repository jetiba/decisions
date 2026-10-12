"""Demo server: runs the LLM loop and the Decision loop side by side and streams every step.

Run: uv run uvicorn agent_demo.server:app --reload
"""

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse

from agent_demo.clients import model_names
from agent_demo.selectors import load_pricing

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parent.parent
SIDES = ("llm", "decision")

SCENARIOS = [
    {
        "id": "refund",
        "title": "Damaged order refund",
        "task": "Customer jane@example.com says order 1042 arrived damaged. Check the order, refund it if eligible, and confirm to the customer by email.",
    },
    {"id": "kb", "title": "Simple KB question", "task": "How do I reset my password? Answer from the knowledge base."},
    {
        "id": "export",
        "title": "Export and follow-up",
        "task": "Export last month's orders to warehouse://analytics/orders_2026_09 and open a normal-priority ticket for the data team confirming it.",
    },
    {
        "id": "sql",
        "title": "Revenue summary",
        "task": "Find the top products by revenue and email the summary to finance@contoso.com.",
    },
    {"id": "ambiguous", "title": "Ambiguous problem", "task": "Something is wrong with order 2077. Figure out what and fix it."},
]

app = FastAPI()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config() -> dict:
    return {
        "scenarios": SCENARIOS,
        "models": model_names(),
        "prices_set": {m: p["input"] is not None and p["output"] is not None for m, p in load_pricing().items()},
    }


async def _pump(side: str, proc: asyncio.subprocess.Process, queue: asyncio.Queue) -> None:
    async for line in proc.stdout:
        queue.put_nowait({**json.loads(line), "side": side})
    queue.put_nowait({"type": "eof", "side": side})


async def _drain_stderr(proc: asyncio.subprocess.Process, tail: list[str]) -> None:
    async for line in proc.stderr:
        tail.append(line.decode(errors="replace").rstrip())
        del tail[:-20]


@app.get("/api/run")
async def run(task: str = Query(min_length=1, max_length=1000)) -> StreamingResponse:
    async def stream():
        yield 'data: {"type": "warming"}\n\n'
        queue: asyncio.Queue = asyncio.Queue()
        procs: dict[str, asyncio.subprocess.Process] = {}
        stderr_tail: dict[str, list[str]] = {s: [] for s in SIDES}
        bg: list[asyncio.Task] = []
        try:
            # Each loop runs in its own process: own interpreter, GIL, connection pool and token cache.
            for side in SIDES:
                p = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "agent_demo.worker", side,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=ROOT,
                )
                procs[side] = p
                p.stdin.write(json.dumps({"task": task}).encode() + b"\n")
                await p.stdin.drain()
                bg += [asyncio.create_task(_pump(side, p, queue)), asyncio.create_task(_drain_stderr(p, stderr_tail[side]))]

            ready: set[str] = set()
            done: set[str] = set()
            released = False
            while len(done) < 2:
                ev = await queue.get()
                side, kind = ev["side"], ev["type"]
                if kind == "eof":
                    if side not in done:  # worker died without reporting
                        msg = " | ".join(stderr_tail[side][-3:]) or "worker exited unexpectedly"
                        for e in ({"type": "error", "message": msg}, {"type": "done", "status": "error", "wall_ms": 0}):
                            yield f"data: {json.dumps({**e, 'side': side})}\n\n"
                        done.add(side)
                elif kind == "ready":
                    ready.add(side)
                else:
                    yield f"data: {json.dumps(ev)}\n\n"
                    if kind == "done":
                        done.add(side)
                # Release both loops at the same instant once each is warmed (or has failed).
                if not released and len(ready | done) == 2:
                    released = True
                    for s in ready:
                        procs[s].stdin.write(b"go\n")
                        await procs[s].stdin.drain()
        finally:
            for p in procs.values():
                if p.returncode is None:
                    p.kill()
            for t in bg:
                t.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream")
