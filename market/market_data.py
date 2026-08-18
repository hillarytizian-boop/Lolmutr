"""Binance-backed crypto snapshot for the cockpit, risk module, and TA note."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.binance.feed import MarketFeed
from app.binance.indicators import compute_indicators
from app.binance.symbols import to_binance
from market.news import NewsBundle, fetch_news_bundle
from market.sentiment import SentimentBundle, fetch_sentiment


@dataclass
class SymbolSnapshot:
    symbol: str
    price: float
    change_pct: float
    volume: float
    atr: float
    atr_pct: float
    rsi: float
    ema20: float
    ema50: float
    trend: str
    stale: bool
    fetched_at: float
    high_24h: float = 0.0
    low_24h: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketContext:
    snapshots: dict[str, SymbolSnapshot] = field(default_factory=dict)
    news: NewsBundle = field(default_factory=NewsBundle)
    sentiment: SentimentBundle | None = None
    feed: str = "unknown"
    latency_ms: float = 0.0
    connected: bool = False
    note: str = ""


class CryptoMarketAdapter:
    def __init__(self, feed: MarketFeed | None = None) -> None:
        self.feed = feed or MarketFeed()

    def ping(self) -> bool:
        try:
            return bool(self.feed.ping())
        except Exception:
            return False

    def snapshot(self, symbol: str, interval: str = "1h") -> SymbolSnapshot:
        pair = to_binance(symbol)
        t0 = time.monotonic()
        ticker = self.feed.ticker(pair)
        candles = self.feed.klines(pair, interval=interval, limit=200)
        ind = compute_indicators(candles, change_24h=float(ticker.get("change_pct") or 0))
        if ind.last_close > ind.ema20 > ind.ema50:
            trend = "BULLISH"
        elif ind.last_close < ind.ema20 < ind.ema50:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"
        stale = (time.monotonic() - t0) > 20
        return SymbolSnapshot(
            symbol=pair,
            price=ind.last_close,
            change_pct=float(ticker.get("change_pct") or 0),
            volume=ind.volume,
            atr=ind.atr,
            atr_pct=ind.atr_pct,
            rsi=ind.rsi,
            ema20=ind.ema20,
            ema50=ind.ema50,
            trend=trend,
            stale=stale,
            fetched_at=time.time(),
            high_24h=float(ticker.get("high") or 0),
            low_24h=float(ticker.get("low") or 0),
        )

    def context(self, symbols: list[str], interval: str = "1h") -> MarketContext:
        t0 = time.monotonic()
        connected = self.ping()
        snaps: dict[str, SymbolSnapshot] = {}
        for symbol in symbols:
            try:
                snaps[to_binance(symbol)] = self.snapshot(symbol, interval)
            except Exception:
                continue
        news = fetch_news_bundle()
        sentiment = fetch_sentiment()
        note_parts = []
        if news.note:
            note_parts.append(news.note)
        if sentiment.note:
            note_parts.append(sentiment.note)
        btc = snaps.get("BTCUSDT")
        if btc:
            note_parts.append(
                f"BTCUSDT last {btc.price:.4g} trend={btc.trend} RSI={btc.rsi:.1f} "
                f"24h={btc.change_pct:+.2f}% (adapter observation, not a trade)."
            )
        return MarketContext(
            snapshots=snaps,
            news=news,
            sentiment=sentiment,
            feed=getattr(self.feed, "source", "unknown"),
            latency_ms=(time.monotonic() - t0) * 1000.0,
            connected=connected,
            note=" ".join(note_parts),
        )
