# Puzzle arena: an LLM vs Microsoft-Decision-1 on the 100-squares puzzle

Two agents solve the same puzzle in the same GitHub Copilot SDK harness and a dashboard shows them playing live.

**Puzzle:** a 10x10 board. Place `1` on any square, then move so that each next number lands 3 squares horizontally/vertically or 2 diagonally from the previous one, on an empty square. Goal: fill 1 to 100.

| Agent | Model | How it plugs into the Copilot SDK |
| --- | --- | --- |
| LLM (selectable: `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna`) | chat model | Responses API provider |
| Microsoft-Decision-1 | decision model | a local OpenAI-compatible shim (`shim.py`) turns each request into one Decision-1 `choice` question and replies with the selected tool call |

Both agents get the same prompts, tools (`move`, `undo`), game engine and metrics. The shim contains no game logic.

## Run

Needs [`uv`](https://docs.astral.sh/uv/) and `az login` (Entra ID, the same resource as the rest of this repo).

```bash
cd puzzle_arena
./run.sh          # uv sync, downloads the Copilot runtime once, starts the server
```

Open http://127.0.0.1:8765, pick the LLM, the options and the number of games, then **Start batch**. Results are appended to `results/runs.jsonl`.

Without the script: `uv sync && uv run python -m copilot download-runtime && uv run python server.py`.

Configuration (see `config.py`): the Foundry resource is taken from `AZURE_ENDPOINT` in the repo-level `.env` (git-ignored; copy `.env.example`), or from a `puzzle_arena/.env`. It must be the resource that hosts these deployments. The Decision-1 deployment is `DEPLOYMENT_NAME` from the same file. Optional environment variables: `ARENA_PORT`, `ARENA_ASTRA_DEPLOYMENT`, `ARENA_SOL_DEPLOYMENT`, `ARENA_LUNA_DEPLOYMENT`, `ARENA_DECISION_DEPLOYMENT`.

## Options (per batch)

| Option | Off means |
| --- | --- |
| Strategy text | prompt has no Warnsdorff/backtracking advice |
| Onward counts | candidates do not show how many onward moves each has |
| Legal-move filter | models see every empty square and can pick illegal moves |
| Auto-play forced steps | single-option steps are not played by the harness (needs the filter) |
| Failed-move memory | squares that led to a dead end are offered again after `undo` |
| Illegal-move memory | (off by default, needs the filter off) rejected squares are not offered again from the same position |

Presets: guided (all helpers on), no strategy, no legal filter, raw.

## Files

```text
server.py     aiohttp server, SSE, batch orchestration, results
agents.py     Copilot SDK harness: sessions, tools, watchdog, metrics
shim.py       Decision-1 adapter for the SDK (no game logic)
game.py       rules engine and tool results
options.py    toggles, presets
prompts.py    prompts shared by both agents
auth.py       cached Entra token (shared by both agents)
diag.py       event-loop lag monitor (saved with every result)
static/       dashboard
```

## Notes

- Both agents run in one Python process and one asyncio loop (each has its own Copilot runtime process). Measured event-loop lag during a game is about 1 ms, and is stored with each result. Use "one after the other" in the UI to also rule out machine and network sharing.
- Decision-1 returns slightly different probabilities for identical requests, so near-ties can flip and the same game seed can play out differently between runs.
- In raw configurations (no legal-move filter) Decision-1 mostly cannot find reachable squares. It scores options; it does not compute geometry.
