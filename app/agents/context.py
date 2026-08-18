"""Public context feeds the sentiment / news desks can use without API keys."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)
_TIMEOUT = 10.0


_FG_FALLBACK = {"value": 47.0, "classification": "Neutral", "source": "fallback"}


def fetch_fear_greed() -> dict[str, Any] | None:
    try:
        response = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=_TIMEOUT)
        response.raise_for_status()
        row = (response.json().get("data") or [None])[0]
        if not row:
            return dict(_FG_FALLBACK)
        return {
            "value": float(row.get("value")),
            "classification": row.get("value_classification"),
            "source": "alternative.me",
        }
    except Exception as exc:
        logger.info("Fear & Greed unavailable: %s", exc)
        return dict(_FG_FALLBACK)


def fetch_news(limit: int = 20) -> list[dict[str, Any]]:
    try:
        response = httpx.get(
            "https://min-api.cryptocompare.com/data/v2/news/",
            params={"lang": "EN"},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        items = response.json().get("Data") or []
        out = []
        for item in items[:limit]:
            out.append(
                {
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "source": item.get("source") or "",
                    "body": (item.get("body") or "")[:280],
                    "published": item.get("published_on"),
                }
            )
        return out
    except Exception as exc:
        logger.info("CryptoCompare news unavailable: %s", exc)
        return []
