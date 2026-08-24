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

_INTERVAL_SEC = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


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
    close_time_ms: int = 0
    timestamp: str = ""
    timeframes: dict[str, dict[str, float]] = field(default_factory=dict)
    funding_rate: float | None = None
    open_interest: float | None = None
    bid: float = 0.0
    ask: float = 0.0
    volatility: float = 0.0
    structure: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


@dataclass
class MarketContext:
    snapshots: dict[str, SymbolSnapshot] = field(default_factory=dict)
    news: NewsBundle = field(default_factory=NewsBundle)
    sentiment: SentimentBundle | None = None
    feed: str = "unknown"
    latency_ms: float = 0.0
    connected: bool = False
    note: str = ""
    error: str = ""


def _stale(close_time_ms: int, interval: str, fetched_at: float) -> bool:
    if fetched_at and (time.time() - fetched_at) > 120:
        return True
    if close_time_ms <= 0:
        return True
    step = _INTERVAL_SEC.get(interval, 3600)
    # Allow the current unfinished bar plus one extra bar of slack.
    age = time.time() - (close_time_ms / 1000.0)
    return age > (step * 2 + 30)


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
        if not candles:
            raise RuntimeError(f"no klines for {pair}")
        last = candles[-1]
        age_fetch = time.monotonic() - t0
        close_ms = int(getattr(last, "close_time", 0) or 0)
        stale = _stale(close_ms, interval, time.time()) or age_fetch > 25
        ind = compute_indicators(candles, change_24h=float(ticker.get("change_pct") or 0))
        if ind.last_close > ind.ema20 > ind.ema50:
            trend = "BULLISH"
        elif ind.last_close < ind.ema20 < ind.ema50:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"
        if ind.last_close > ind.high_20 * 0.995:
            structure = "breakout"
        elif ind.last_close < ind.low_20 * 1.005:
            structure = "breakdown"
        else:
            structure = "range"
        extra: dict[str, dict[str, float]] = {interval: {"close": ind.last_close, "rsi": ind.rsi}}
        for tf in ("4h", "1d"):
            if tf == interval:
                continue
            try:
                rows = self.feed.klines(pair, interval=tf, limit=80)
                extra_ind = compute_indicators(rows, change_24h=0.0)
                extra[tf] = {"close": extra_ind.last_close, "rsi": extra_ind.rsi, "atr": extra_ind.atr}
            except Exception:
                continue
        bid = ask = 0.0
        try:
            book = self.feed.depth(pair, limit=5)
            if book.get("bids"):
                bid = float(book["bids"][0][0])
            if book.get("asks"):
                ask = float(book["asks"][0][0])
        except Exception:
            pass
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
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
            close_time_ms=close_ms,
            timestamp=ts,
            timeframes=extra,
            funding_rate=None,  # spot — not invented
            open_interest=None,  # spot — not invented
            bid=bid,
            ask=ask,
            volatility=ind.atr_pct,
            structure=structure,
        )

    def context(self, symbols: list[str], interval: str = "1h") -> MarketContext:
        t0 = time.monotonic()
        error = ""
        try:
            connected = self.ping()
        except Exception as exc:
            connected = False
            error = str(exc)[:200]
        snaps: dict[str, SymbolSnapshot] = {}
        for symbol in symbols:
            try:
                snaps[to_binance(symbol)] = self.snapshot(symbol, interval)
            except Exception as exc:
                error = error or str(exc)[:200]
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
                f"24h={btc.change_pct:+.2f}% ts={btc.timestamp} "
                f"(adapter observation, not a trade)."
            )
        if not snaps:
            note_parts.append("Market snapshots empty — not inventing prices.")
        return MarketContext(
            snapshots=snaps,
            news=news,
            sentiment=sentiment,
            feed=getattr(self.feed, "source", "unknown"),
            latency_ms=(time.monotonic() - t0) * 1000.0,
            connected=connected and bool(snaps),
            note=" ".join(note_parts),
            error=error,
        )
