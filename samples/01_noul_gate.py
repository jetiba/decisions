"""Noul: yes/no gate returning a probability (0-1)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_client import DecisionClient, noul

client = DecisionClient()

replies = [
    "I refunded your $200. You don't need to contact billing.",
    "Thanks for reaching out. I've forwarded your case to our billing team.",
]

for reply in replies:
    result = client.decide(
        reply,
        {
            "promises_refund": noul(
                "Does this reply promise the customer a refund?",
                {"true": "Commits to returning money", "false": "Makes no commitment about money"},
            )
        },
    )
    print(reply)
    print(json.dumps(result, indent=2), "\n")
