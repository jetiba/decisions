"""Evaluate a choice question on labeled data: accuracy, latency, abstention threshold, option-order sensitivity."""

import json
import random
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from decision_client import DecisionClient, choice

client = DecisionClient()

OPTIONS = {
    "billing": "Charges, invoices, and refunds",
    "engineering": "Bugs, errors, and outages",
    "support": "How-to and account questions",
}
THRESHOLDS = [0.0, 0.5, 0.8, 0.9, 0.99]

examples = [json.loads(line) for line in (ROOT / "data" / "tickets.jsonl").read_text().splitlines() if line]


def classify(text: str, options: dict[str, str]) -> tuple[str, float, float]:
    start = perf_counter()
    result = client.decide(text, {"team": choice("Which team should handle this ticket?", options)})
    ms = (perf_counter() - start) * 1000
    ans = result["answers"]["team"]
    return ans["choice"], ans["confidence"], ms


def run(options: dict[str, str]) -> list[tuple[dict, str, float, float]]:
    rows = []
    for ex in examples:
        pred, conf, ms = classify(ex["text"], options)
        rows.append((ex, pred, conf, ms))
    return rows


rows = run(OPTIONS)
print(f"Accuracy: {sum(p == e['label'] for e, p, _, _ in rows) / len(rows):.1%}")
print(f"Median latency: {median(r[3] for r in rows):.0f} ms\n")

print("threshold  auto-handled  accuracy-on-handled  sent-to-human")
for t in THRESHOLDS:
    handled = [r for r in rows if r[2] >= t]
    acc = sum(p == e["label"] for e, p, _, _ in handled) / len(handled) if handled else float("nan")
    print(f"{t:>9.2f}  {len(handled):>12}  {acc:>19.1%}  {len(rows) - len(handled):>13}")

print("\nMisclassified / low confidence:")
for e, p, c, _ in rows:
    if p != e["label"] or c < 0.8:
        print(f"  expected={e['label']:<12} predicted={p:<12} conf={c:.2f}  {e['text']}")

# Option order sensitivity: shuffle option order and compare predictions.
items = list(OPTIONS.items())
random.Random(0).shuffle(items)
shuffled_rows = run(dict(items))
changed = sum(a[1] != b[1] for a, b in zip(rows, shuffled_rows))
print(f"\nPredictions changed after reordering options: {changed}/{len(rows)}")
