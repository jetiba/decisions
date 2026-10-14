"""Foundry / arena configuration. The resource comes from AZURE_ENDPOINT (shared .env of this repo)."""
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))
load_dotenv(os.path.join(HERE, "..", ".env"))  # the repo-level .env (git-ignored)

_endpoint = os.getenv("AZURE_ENDPOINT", "")
RESOURCE = (urlparse(_endpoint).hostname or "").split(".")[0]
if not RESOURCE or RESOURCE.startswith("<"):
    raise SystemExit("Set AZURE_ENDPOINT (https://<resource>.services.ai.azure.com) in the repo .env or puzzle_arena/.env")
OPENAI_HOST = f"https://{RESOURCE}.openai.azure.com"          # chat / responses models
FOUNDRY_HOST = f"https://{RESOURCE}.services.ai.azure.com"     # Decision-1 "systemone" API
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"

# LLMs selectable for the chat-model agent (key = UI value, value = Foundry deployment name)
LLMS = {
    "gpt-6-astra": os.getenv("ARENA_ASTRA_DEPLOYMENT", "gpt-6-astra"),
    "gpt-6.1-sol": os.getenv("ARENA_SOL_DEPLOYMENT", "gpt-6.1-sol"),
    "gpt-6-luna": os.getenv("ARENA_LUNA_DEPLOYMENT", "gpt-6-luna"),
}
DEFAULT_LLM = "gpt-6-astra"
DECISION_DEPLOYMENT = os.getenv("ARENA_DECISION_DEPLOYMENT") or os.getenv("DEPLOYMENT_NAME", "Decision-1")

PORT = int(os.getenv("ARENA_PORT", "8765"))
SHIM_BASE_URL = f"http://127.0.0.1:{PORT}/shim/v1"

RESULTS_FILE = os.path.join(HERE, "results", "runs.jsonl")
COPILOT_HOME = os.path.join(HERE, ".copilot-home")
