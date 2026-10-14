#!/usr/bin/env bash
# Starts the arena (requires `az login`). UI: http://127.0.0.1:8765
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
uv sync --quiet
uv run --quiet python -m copilot download-runtime  # cached after the first run
exec uv run python server.py
