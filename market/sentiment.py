"""Optional Fear & Greed. Missing data is marked unavailable — never faked."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("sentiment")
_TIMEOUT = 10.0


@dataclass
class SentimentBundle:
    value: float | None
    classification: str | None
    source: str
    status: str
    note: str = ""


def fetch_sentiment() -> SentimentBundle:
    try:
        response = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=_TIMEOUT)
        response.raise_for_status()
        row = (response.json().get("data") or [None])[0]
        if not row:
            raise RuntimeError("empty payload")
        return SentimentBundle(
            value=float(row.get("value")),
            classification=row.get("value_classification"),
            source="alternative.me",
            status="ONLINE",
        )
    except Exception as exc:
        logger.info("Fear & Greed unavailable: %s", exc)
        return SentimentBundle(
            value=None,
            classification=None,
            source="none",
            status="DEGRADED",
            note="Fear & Greed feed unavailable. No sentiment number was invented.",
        )
