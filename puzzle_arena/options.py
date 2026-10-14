"""Per-batch behaviour switches. They are applied identically to both agents."""

DEFAULTS = {
    "strategy": True,        # prompt describes Warnsdorff + backtracking (advice only)
    "onward_counts": True,   # each candidate shows how many onward moves its square would have
    "legal_filter": True,    # candidates are only legal moves (otherwise: every empty square, illegal picks allowed)
    "auto_forced": True,     # steps with a single option (forced move / forced undo) are played by the harness
    "failed_memory": True,   # moves that already led to a dead end are not offered again
    "illegal_memory": False, # squares already rejected as illegal from this position are not offered again
}

PRESETS = {
    "guided": dict(DEFAULTS),
    "no_strategy": {**DEFAULTS, "strategy": False},
    "no_legal_filter": {**DEFAULTS, "legal_filter": False, "auto_forced": False},
    "raw": {"strategy": False, "onward_counts": False, "legal_filter": False,
            "auto_forced": False, "failed_memory": False, "illegal_memory": False},
}


def normalize(raw: dict | None) -> dict:
    opts = dict(DEFAULTS)
    for k in DEFAULTS:
        if raw and k in raw:
            opts[k] = bool(raw[k])
    # Auto-playing forced steps requires the harness to know the legal moves, so it needs the filter.
    opts["auto_forced"] = opts["auto_forced"] and opts["legal_filter"]
    opts["illegal_memory"] = opts["illegal_memory"] and not opts["legal_filter"]  # nothing is illegal when filtered
    return opts
