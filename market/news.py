"""Optional crypto news. Failures are logged once and never fabricate headlines."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("news")
_TIMEOUT = 10.0
_QUIET_FOR = 900.0
_last_fail: dict[str, float] = {}

_RSS_FEEDS = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
)


def _note_fail(provider: str, exc: Exception) -> None:
    now = time.monotonic()
    prev = _last_fail.get(provider, 0.0)
    if now - prev >= _QUIET_FOR:
        logger.warning("%s unavailable: %s — continuing without that source", provider, exc)
        _last_fail[provider] = now
    else:
        logger.debug("%s still unavailable: %s", provider, exc)


@dataclass
class NewsBundle:
    headlines: list[dict[str, Any]] = field(default_factory=list)
    providers_ok: list[str] = field(default_factory=list)
    providers_down: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def status(self) -> str:
        if self.providers_ok:
            return "ONLINE"
        if self.providers_down:
            return "DEGRADED"
        return "OFFLINE"


def _cryptocompare(limit: int) -> list[dict[str, Any]]:
    response = httpx.get(
        "https://min-api.cryptocompare.com/data/v2/news/",
        params={"lang": "EN"},
        timeout=_TIMEOUT,
    )
    if response.status_code == 401:
        raise RuntimeError("401 Unauthorized")
    response.raise_for_status()
    items = response.json().get("Data") or []
    out = []
    for item in items[:limit]:
        out.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "source": item.get("source") or "cryptocompare",
                "body": (item.get("body") or "")[:280],
            }
        )
    return out


def _rss(url: str, source: str, limit: int) -> list[dict[str, Any]]:
    response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "LolmutrDesk/1.0"})
    response.raise_for_status()
    root = ET.fromstring(response.text)
    items = root.findall(".//item")
    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if not title:
            continue
        out.append({"title": title, "url": link, "source": source, "body": desc[:280]})
    return out


def fetch_news_bundle(limit: int = 12) -> NewsBundle:
    bundle = NewsBundle()
    try:
        rows = _cryptocompare(limit)
        if rows:
            bundle.headlines.extend(rows)
            bundle.providers_ok.append("cryptocompare")
    except Exception as exc:
        _note_fail("CryptoCompare", exc)
        bundle.providers_down.append("cryptocompare")

    if not bundle.headlines:
        for name, url in _RSS_FEEDS:
            try:
                rows = _rss(url, name, limit)
                if rows:
                    bundle.headlines.extend(rows[:limit])
                    bundle.providers_ok.append(name)
                    break
            except Exception as exc:
                _note_fail(name, exc)
                bundle.providers_down.append(name)

    if not bundle.headlines:
        bundle.note = (
            "No news provider returned headlines. TradingAgents was told the "
            "wire is unavailable. No headlines were fabricated."
        )
    return bundle
