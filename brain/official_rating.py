# From TauricResearch/TradingAgents tradingagents/agents/utils/rating.py
from __future__ import annotations

import re

RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)
_RATING_SET = {r.lower() for r in RATINGS_5_TIER}
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)


def parse_rating(text: str, default: str = "Hold") -> str:
    if not text:
        return default
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return m.group(1).capitalize()
    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                return clean.capitalize()
    return default
