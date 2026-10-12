"""Minimal client for Microsoft-Decision-1 (systemone) on a Foundry resource."""

import os
import threading
import time
from typing import Any

import requests
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
TIMEOUT_SECONDS = 60


def noul(instructions: str, criteria: dict[str, str] | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    return q


def choice(instructions: str, options: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score(instructions: str, levels: list[str]) -> dict[str, Any]:
    """Levels go from lowest to highest."""
    return {"type": "score", "instructions": instructions, "criteria": levels}


class DecisionAPIError(RuntimeError):
    def __init__(self, status_code: int, body: str, retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {status_code}: {body}")
        self.status_code = status_code
        self.retry_after = retry_after


class DecisionClient:
    def __init__(
        self,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.endpoint = (endpoint or os.environ["AZURE_ENDPOINT"]).rstrip("/")
        self.deployment = deployment or os.environ["DEPLOYMENT_NAME"]
        self.api_key = api_key or os.environ.get("AZURE_API_KEY")
        self._credential = None if self.api_key else DefaultAzureCredential()
        self._session = requests.Session()  # keep-alive, like the OpenAI SDK's pooled client
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = threading.Lock()

    def bearer_token(self) -> str:
        """Entra token cached until 5 minutes before expiry (fetching one shells out to the Azure CLI, ~350 ms)."""
        with self._token_lock:
            if self._token is None or time.time() > self._token_expires - 300:
                tok = self._credential.get_token(TOKEN_SCOPE)
                self._token, self._token_expires = tok.token, tok.expires_on
            return self._token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.bearer_token()}"
        return headers

    def decide(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Return the full response payload (answers, model, usage)."""
        resp = self._session.post(
            f"{self.endpoint}/providers/microsoft/v1/systemone",
            headers=self._headers(),
            json={"model": self.deployment, "state": state, "questions": questions},
            timeout=TIMEOUT_SECONDS,
        )
        if not resp.ok:
            raise DecisionAPIError(resp.status_code, resp.text, resp.headers.get("retry-after"))
        return resp.json()
