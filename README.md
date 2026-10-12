# Microsoft-Decision-1 samples

Samples for [Microsoft-Decision-1](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision) in Foundry. The model returns typed decisions (`noul`, `choice`, `score`) with probabilities, not generated text.

## Setup

```bash
uv sync
cp .env.example .env   # adjust values
az login               # Entra ID auth; or set AZURE_API_KEY
```

`AZURE_ENDPOINT` is the Foundry resource endpoint (`https://<resource>.services.ai.azure.com`), not the `/api/projects/...` URL. Requests go to `<endpoint>/providers/microsoft/v1/systemone`, and `model` is the deployment name (`Decision-1`).

## Layout

| File | Purpose |
| --- | --- |
| `decision_client.py` | Client plus `noul()`, `choice()`, `score()` question builders |
| `samples/01_noul_gate.py` | Yes/no gate, returns probability |
| `samples/02_choice_routing.py` | Single-label classification with per-option probabilities |
| `samples/03_score_priority.py` | Ordered scale; returns probability-weighted score |
| `samples/04_combined.py` | Several questions over one JSON state in one request |
| `samples/05_evaluate_with_thresholds.py` | Labeled data (`data/tickets.jsonl`): accuracy, latency, threshold/abstention tradeoff, option-order sensitivity |
| `samples/06_gate_route_escalate.py` | Gate, route, and escalate pattern in front of an LLM |

Run any sample with `uv run samples/01_noul_gate.py`. Add packages with `uv add <package>`.

## Response shapes

- `noul`: `{"type": "noul", "noul": 0.99}`
- `choice`: `{"choice": "engineering", "confidence": 0.99, "probabilities": {...}}`
- `score`: `{"score": 2.77, "confidence": 0.70, "legend": {...}, "probabilities": {...}}`
