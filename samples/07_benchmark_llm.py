"""Benchmark Decision-1 against LLM deployments on the same labeled choice task.

Compares accuracy, latency, tokens, cost, and determinism (same input, repeated runs).
Usage: uv run samples/07_benchmark_llm.py [--repeats 3] [--llms gpt-6-luna,gpt-6.1-sol]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from agent_demo.selectors import cost_usd
from decision_client import DecisionClient, choice
from guard.guards import call_with_backoff

OPTIONS = {
    "billing": "Charges, invoices, and refunds",
    "engineering": "Bugs, errors, and outages",
    "support": "How-to and account questions",
}
INSTRUCTIONS = "Which team should handle this ticket?"

SCHEMA = {
    "type": "json_schema",
    "name": "decision",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"choice": {"type": "string", "enum": list(OPTIONS)}},
        "required": ["choice"],
        "additionalProperties": False,
    },
}
SYSTEM_PROMPT = (
    f"{INSTRUCTIONS} Select exactly one option.\nOptions:\n"
    + "\n".join(f"- {k}: {v}" for k, v in OPTIONS.items())
)

examples = [json.loads(line) for line in (ROOT / "data" / "tickets.jsonl").read_text().splitlines() if line]


def make_decision_runner(client: DecisionClient):
    def run(text: str) -> tuple[str, int, int]:
        result = client.decide(text, {"team": choice(INSTRUCTIONS, OPTIONS)})
        u = result["usage"]
        return result["answers"]["team"]["choice"], u["input_tokens"], u["output_tokens"]

    return run


def make_llm_runner(openai_client: OpenAI, deployment: str):
    # gpt-5/6 are reasoning models: no temperature, and they need the Responses API.
    kwargs = (
        {"reasoning": {"effort": os.environ.get("LLM_REASONING_EFFORT", "low")}}
        if deployment.startswith(("gpt-5", "gpt-6"))
        else {"temperature": 0}
    )

    def run(text: str) -> tuple[str, int, int]:
        resp = openai_client.responses.create(
            model=deployment,
            input=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            text={"format": SCHEMA},
            **kwargs,
        )
        return json.loads(resp.output_text)["choice"], resp.usage.input_tokens, resp.usage.output_tokens

    return run


def benchmark(name: str, run, repeats: int) -> dict:
    run(examples[0]["text"])  # warm-up (connection, backend cold start); not measured
    latencies, tokens, costs, retries, correct = [], [], [], 0, 0
    outputs: dict[int, list[str]] = {i: [] for i in range(len(examples))}
    for _ in range(repeats):
        for i, ex in enumerate(examples):
            (pred, tin, tout), ms, r = call_with_backoff(lambda: run(ex["text"]))  # waiting on 429s is not timed
            latencies.append(ms)
            tokens.append(tin + tout)
            costs.append(cost_usd(name, tin, tout))
            retries += r
            correct += pred == ex["label"]
            outputs[i].append(pred)
    total = len(examples) * repeats
    latencies.sort()
    return {
        "model": name,
        "accuracy": correct / total,
        "p50_ms": median(latencies),
        "p95_ms": latencies[int(0.95 * (len(latencies) - 1))],
        "avg_tokens": sum(tokens) / len(tokens),
        "cost_per_1k": None if None in costs else sum(costs) / len(costs) * 1000,
        "retries": retries,
        "consistent": sum(len(set(v)) == 1 for v in outputs.values()) / len(outputs),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--llms",
        default=os.environ.get("COMPARE_LLMS", "gpt-6-luna,gpt-6.1-sol"),
        help="Comma-separated deployment names in the same Foundry resource (Responses API)",
    )
    args = parser.parse_args()

    decision = DecisionClient()
    openai_client = OpenAI(
        base_url=f"{decision.endpoint}/openai/v1/",
        api_key=decision.api_key or decision.bearer_token,  # cached token: no per-call `az` subprocess in the timing
        max_retries=0,
    )

    contenders = {decision.deployment: make_decision_runner(decision)}
    for name in filter(None, (n.strip() for n in args.llms.split(","))):
        contenders[name] = make_llm_runner(openai_client, name)

    results = [benchmark(name, run, args.repeats) for name, run in contenders.items()]

    print(f"\n{len(examples)} examples x {args.repeats} repeats\n")
    print(f"{'model':<20}{'accuracy':>10}{'p50 ms':>9}{'p95 ms':>9}{'tokens/req':>12}{'$/1k req':>11}{'consistent':>12}")
    for r in results:
        cost = f"${r['cost_per_1k']:.4f}" if r["cost_per_1k"] is not None else "n/a"
        print(
            f"{r['model']:<20}{r['accuracy']:>10.1%}{r['p50_ms']:>9.0f}{r['p95_ms']:>9.0f}"
            f"{r['avg_tokens']:>12.0f}{cost:>11}{r['consistent']:>12.0%}"
        )


main()
