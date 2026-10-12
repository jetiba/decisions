"""Shared, long-lived clients so both loops use warm, pooled connections and cached tokens."""

import os
from functools import lru_cache

from openai import OpenAI

from decision_client import DecisionClient


@lru_cache(maxsize=1)
def decision_client() -> DecisionClient:
    return DecisionClient()


@lru_cache(maxsize=1)
def openai_client() -> OpenAI:
    d = decision_client()
    # max_retries=0: the SDK's silent 429 retries would add hidden latency; Decision-1 has none.
    return OpenAI(
        base_url=f"{d.endpoint}/openai/v1/",
        api_key=d.api_key or d.bearer_token,
        timeout=60,
        max_retries=0,
    )


def warm_up(side: str) -> None:
    """Tiny requests (token, TLS, server-side cold start) for the models this side uses, outside the measured loop."""
    from decision_client import noul

    models = model_names()
    d, c = decision_client(), openai_client()
    names = [models["llm"]] if side == "llm" else [models["args"]]
    if side == "decision":
        d.decide("ping", {"q": noul("Is this a greeting?")})
    for name in names:
        c.responses.create(model=name, input="ping", max_output_tokens=16, reasoning={"effort": "low"})


def model_names() -> dict[str, str]:
    return {
        "llm": os.environ.get("LLM_DEPLOYMENT", "gpt-6.1-sol"),
        "decision": decision_client().deployment,
        "args": os.environ.get("ARG_LLM_DEPLOYMENT", "gpt-6-luna"),
    }
