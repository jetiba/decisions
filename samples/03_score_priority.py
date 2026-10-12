"""Score: place an item on an ordered scale (probability-weighted level index)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_client import DecisionClient, score

client = DecisionClient()

LEVELS = ["Cosmetic", "Minor", "Major", "Critical"]

for incident in [
    "Checkout is down for all EU customers since 09:00.",
    "The footer link color is slightly off on the pricing page.",
]:
    result = client.decide(incident, {"severity": score("How severe is this incident?", LEVELS)})
    print(incident)
    print(json.dumps(result["answers"], indent=2), "\n")
