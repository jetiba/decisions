"""Combine choice + score + noul in one request over structured (JSON) state."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_client import DecisionClient, choice, noul, score

client = DecisionClient()

state = {
    "message": "Checkout is down again. This is my third request.",
    "customer_contact_count": 3,
}

result = client.decide(
    state,
    {
        "team": choice(
            "Which team should handle this request?",
            {
                "billing": "Charges, invoices, and refunds",
                "engineering": "Bugs, errors, and outages",
                "support": "How-to and account questions",
            },
        ),
        "severity": score("How severe is this issue?", ["Cosmetic", "Minor", "Major", "Critical"]),
        "repeat_contact": noul("Has the customer contacted support before?"),
    },
)
print(json.dumps(result, indent=2))
