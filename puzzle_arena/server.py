"""Arena server: runs the Copilot SDK agents, streams live state to the UI, stores results."""
import asyncio
import json
import os
import time
import uuid

from aiohttp import web

import agents
import auth
import config
import diag
import shim
from options import PRESETS, normalize

STATIC = os.path.join(config.HERE, "static")
clients: set[asyncio.Queue] = set()
live: dict[str, dict] = {}
batch: dict = {"running": False, "id": None, "config": None}
stop_evt = asyncio.Event()
tasks: list[asyncio.Task] = []


def fresh_live(key: str) -> dict:
    return {"agent": key, "label": agents.AGENTS[key]["label"], "game": 0, "status": "idle",
            "grid": [[0] * 10 for _ in range(10)], "filled": 0, "illegal": 0, "undos": 0,
            "tool_calls": 0, "started_at": None, "elapsed": 0, "last": None, "message": None,
            "completed": 0, "solved": 0}


def broadcast(ev: dict) -> None:
    data = f"data: {json.dumps(ev)}\n\n"
    for q in list(clients):
        q.put_nowait(data)


def emit(ev: dict) -> None:
    st = live[ev["agent"]]
    t = ev["type"]
    if t == "game_start":
        st.update(grid=[[0] * 10 for _ in range(10)], game=ev["game"], status="running", started_at=time.time(),
                  last=None, message=None)
    elif t == "move":
        st["grid"][ev["r"]][ev["c"]] = ev["n"]
        st["last"] = [ev["r"], ev["c"]]
    elif t == "undo":
        st["grid"][ev["r"]][ev["c"]] = 0
        st["last"] = None
    elif t == "illegal":
        st["message"] = ev.get("message")
    for k in ("filled", "illegal", "undos", "tool_calls", "elapsed"):
        if k in ev:
            st[k] = ev[k]
    broadcast({**ev, "started_at": st["started_at"]})


def load_results() -> list[dict]:
    if not os.path.exists(config.RESULTS_FILE):
        return []
    with open(config.RESULTS_FILE) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_result(res: dict) -> None:
    os.makedirs(os.path.dirname(config.RESULTS_FILE), exist_ok=True)
    with open(config.RESULTS_FILE, "a") as f:
        f.write(json.dumps(res) + "\n")


async def run_agent(key: str, cfg: dict) -> None:
    agent = agents.with_llm(key, cfg["llm"])
    client = agents.new_client()
    try:
        await client.start()
        for g in range(1, cfg["games"] + 1):
            if stop_evt.is_set():
                break
            res = await agents.run_game(client, agent, g, emit, cfg["timeout_s"], cfg["max_tool_calls"], stop_evt, cfg["options"])
            res["batch_id"] = batch["id"]
            if res["status"] != "stopped":
                save_result(res)
                live[key]["completed"] += 1
                live[key]["solved"] += int(res["solved"])
            live[key]["status"] = res["status"]
            broadcast({"type": "game_end", "agent": key, "result": {k: v for k, v in res.items() if k != "board"}})
    except Exception as exc:  # noqa: BLE001
        live[key]["status"] = "error"
        broadcast({"type": "agent_error", "agent": key, "message": repr(exc)})
    finally:
        try:
            await asyncio.wait_for(client.stop(), 15)
        except Exception:  # noqa: BLE001
            pass


async def run_batch(cfg: dict) -> None:
    try:
        await asyncio.to_thread(auth.token)  # warm the token cache before any timed call
        diag.start()
        if cfg["sequential"]:
            for k in cfg["agents"]:
                await run_agent(k, cfg)
        else:
            await asyncio.gather(*(run_agent(k, cfg) for k in cfg["agents"]))
    finally:
        batch["running"] = False
        broadcast({"type": "batch_end", "batch_id": batch["id"]})


async def start(request: web.Request) -> web.Response:
    if batch["running"]:
        return web.json_response({"error": "a batch is already running"}, status=409)
    body = await request.json() if request.can_read_body else {}
    cfg = {
        "games": int(body.get("games", 10)),
        "timeout_s": float(body.get("timeout_s", 1200)),
        "max_tool_calls": int(body.get("max_tool_calls", 2000)),
        "options": normalize(body.get("options")),
        "llm": body.get("llm") if body.get("llm") in config.LLMS else config.DEFAULT_LLM,
        "sequential": bool(body.get("sequential", False)),
        "agents": [a for a in body.get("agents", ["astra", "decision"]) if a in agents.AGENTS],
    }
    stop_evt.clear()
    batch.update(running=True, id=time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4], config=cfg)
    for k in agents.AGENTS:
        live[k] = fresh_live(k)
    live["astra"]["label"] = cfg["llm"]
    broadcast({"type": "batch_start", "batch_id": batch["id"], "config": cfg})
    tasks.append(asyncio.create_task(run_batch(cfg)))
    return web.json_response({"batch_id": batch["id"], "config": cfg})


async def stop(_: web.Request) -> web.Response:
    stop_evt.set()
    return web.json_response({"ok": True})


async def snapshot(_: web.Request) -> web.Response:
    return web.json_response({"batch": batch, "live": live})


async def results(_: web.Request) -> web.Response:
    return web.json_response(load_results())


async def events(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    q: asyncio.Queue = asyncio.Queue()
    clients.add(q)
    try:
        await resp.write(f"data: {json.dumps({'type': 'snapshot', 'batch': batch, 'live': live})}\n\n".encode())
        while True:
            try:
                await resp.write((await asyncio.wait_for(q.get(), 15)).encode())
            except asyncio.TimeoutError:
                await resp.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        clients.discard(q)
    return resp


async def llms(_: web.Request) -> web.Response:
    return web.json_response({"llms": list(config.LLMS), "default": config.DEFAULT_LLM})


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


def make_app() -> web.Application:
    for k in agents.AGENTS:
        live[k] = fresh_live(k)
    app = web.Application()
    app.add_routes([
        web.get("/api/llms", llms),
        web.get("/", index),
        web.get("/events", events),
        web.get("/api/state", snapshot),
        web.get("/api/results", results),
        web.post("/api/start", start),
        web.post("/api/stop", stop),
        web.post("/shim/v1/chat/completions", shim.chat_completions),
    ])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=config.PORT)
