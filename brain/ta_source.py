"""Locate the official TauricResearch/TradingAgents checkout."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "TradingAgents"


def official_root() -> Path | None:
    if (VENDOR / "tradingagents" / "graph" / "trading_graph.py").exists():
        return VENDOR
    return None


def official_parse_rating():
    root = official_root()
    if root is not None:
        path = str(root)
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            from tradingagents.agents.utils.rating import parse_rating

            return parse_rating
        except Exception:
            pass
    from brain.official_rating import parse_rating

    return parse_rating
