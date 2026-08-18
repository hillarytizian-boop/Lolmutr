"""Legacy wrappers — news/sentiment live in market/ and never fabricate."""

from __future__ import annotations

from typing import Any

from market.news import fetch_news_bundle
from market.sentiment import fetch_sentiment


def fetch_fear_greed() -> dict[str, Any] | None:
    bundle = fetch_sentiment()
    if bundle.value is None:
        return None
    return {
        "value": bundle.value,
        "classification": bundle.classification,
        "source": bundle.source,
    }


def fetch_news(limit: int = 20) -> list[dict[str, Any]]:
    return fetch_news_bundle(limit=limit).headlines
