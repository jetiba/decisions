"""Choice: pick exactly one label; response includes per-option probabilities."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_client import DecisionClient, choice

client = DecisionClient()

OPTIONS = {
    "billing": "Charges, invoices, and refunds",
    "engineering": "Bugs, errors, and outages",
    "support": "How-to and account questions",
}

for ticket in ["The API returns 500 on every call.", "How do I change my email address?"]:
    result = client.decide(ticket, {"team": choice("Which team should handle this ticket?", OPTIONS)})
    print(ticket)
    print(json.dumps(result["answers"], indent=2), "\n")
