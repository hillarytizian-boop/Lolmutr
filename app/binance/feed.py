"""Market-data router: live Binance, then a deterministic demo book.

The sandbox (and some locked-down hosts) reset TLS to api.binance.com.
When that happens the desk keeps working against a seeded replay so the
firm, the chart, and paper fills stay interactive. Local runs that can
reach Binance never see the fallback.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import Any

from app.binance.client import BinanceError, BinancePublic
from app.binance.probe import pick_public_host
from app.binance.symbols import to_binance
from app.config import DEFAULT_WATCHLIST, get_settings
from app.models import Candle

logger = logging.getLogger(__name__)

# Mid-2026-ish anchors used only when Binance is unreachable.
_ANCHORS = {
    "BTCUSDT": 108_450.0,
    "ETHUSDT": 3_920.0,
    "SOLUSDT": 176.4,
    "BNBUSDT": 712.0,
    "XRPUSDT": 0.618,
    "DOGEUSDT": 0.172,
    "ADAUSDT": 0.704,
    "AVAXUSDT": 35.8,
    "LINKUSDT": 17.6,
    "SUIUSDT": 3.42,
}

_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _unit(symbol: str) -> float:
    return hashlib.sha256(symbol.encode()).digest()[0] / 255.0


def _price_at(symbol: str, t_ms: int) -> float:
    """Spot as a pure function of wall-clock so every lookback agrees on last."""
    anchor = _ANCHORS.get(symbol, 25.0)
    u = _unit(symbol)
    t = t_ms / 3_600_000.0
    wave = math.sin(t / (9 + u * 7) + u * 4.0) * 0.08
    wave2 = math.sin(t / (3 + u * 2) + u * 2.1) * 0.03
    wave3 = math.sin(t * 0.17 + u * 8.0) * 0.015
    return max(anchor * 0.35, anchor * (1.0 + wave + wave2 + wave3))


def _candle(symbol: str, open_time: int, step_ms: int, o: float, c: float, i: int) -> Candle:
    u = _unit(symbol)
    wick = abs(c - o) * (0.6 + (i % 5) * 0.15) + c * (0.0008 + u * 0.0006)
    high = max(o, c) + wick
    low = min(o, c) - wick * 0.7
    vol = 80 + (i * 13 + int(u * 90)) % 400
    return Candle(
        open_time=open_time,
        open=o,
        high=high,
        low=max(low, o * 0.2),
        close=c,
        volume=float(vol),
        close_time=open_time + step_ms - 1,
    )


class DemoPublic:
    """Binance-shaped public client backed by a deterministic replay."""

    source = "demo"

    def ping(self) -> bool:
        return True

    def ticker(self, symbol: str) -> dict[str, Any]:
        pair = to_binance(symbol)
        candles = self.klines(pair, "1h", 24)
        last = candles[-1].close
        first = candles[0].open
        change = last - first
        pct = change / first * 100.0 if first else 0.0
        return {
            "symbol": pair,
            "price": last,
            "change": change,
            "change_pct": pct,
            "high": max(c.high for c in candles),
            "low": min(c.low for c in candles),
            "volume": sum(c.volume for c in candles),
            "quote_volume": sum(c.volume * c.close for c in candles),
            "trades": 12_000 + int(_unit(pair) * 8000),
        }

    def tickers(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        wanted = symbols or list(DEFAULT_WATCHLIST)
        rows = [self.ticker(s) for s in wanted]
        rows.sort(key=lambda r: r["quote_volume"], reverse=True)
        return rows

    def klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]:
        pair = to_binance(symbol)
        step = _INTERVAL_MS.get(interval, 3_600_000)
        now = int(time.time() * 1000)
        now = now - (now % step)
        n = max(60, min(limit, 500))
        start = now - step * (n - 1)
        return [
            _candle(
                pair,
                start + i * step,
                step,
                _price_at(pair, start + i * step),
                _price_at(pair, start + (i + 1) * step),
                i,
            )
            for i in range(n)
        ]

    def depth(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        pair = to_binance(symbol)
        last = self.ticker(pair)["price"]
        tick = last * 0.00015
        bids, asks = [], []
        for i in range(limit):
            bids.append([last - tick * (i + 1), 0.4 + i * 0.18])
            asks.append([last + tick * (i + 1), 0.35 + i * 0.16])
        return {"symbol": pair, "last_update_id": int(time.time()), "bids": bids, "asks": asks}

    def price(self, symbol: str) -> float:
        return self.ticker(symbol)["price"]


class MarketFeed:
    """Prefer live Binance; cache the choice so we don't TLS-fail every call."""

    def __init__(self) -> None:
        picked, _ = pick_public_host()
        host = picked or get_settings().public_rest
        self._live = BinancePublic(base=host)
        self._demo = DemoPublic()
        self._backend: str | None = None
        self.last_error = ""

    @property
    def source(self) -> str:
        return self._backend or "unknown"

    def _pick(self) -> BinancePublic | DemoPublic:
        if self._backend == "binance":
            return self._live
        if self._backend == "demo":
            return self._demo
        try:
            self._live.ping()
            self._backend = "binance"
            logger.info("market feed: live Binance %s", self._live.base)
            return self._live
        except BinanceError as exc:
            picked, detail = pick_public_host()
            if picked:
                self._live = BinancePublic(base=picked)
                self._backend = "binance"
                logger.info("market feed: live Binance fallback %s", picked)
                return self._live
            self._backend = "demo"
            self.last_error = detail or str(exc)
            logger.warning("Binance unreachable; using demo feed")
            return self._demo

    def ping(self) -> bool:
        backend = self._pick()
        if backend is self._demo:
            return False
        try:
            return bool(backend.ping())
        except BinanceError:
            self._backend = "demo"
            return False

    def ticker(self, symbol: str) -> dict[str, Any]:
        return self._try("ticker", symbol)

    def tickers(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        return self._try("tickers", symbols)

    def klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]:
        return self._try("klines", symbol, interval, limit)

    def depth(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        return self._try("depth", symbol, limit)

    def price(self, symbol: str) -> float:
        return self._try("price", symbol)

    def _try(self, method: str, *args):
        backend = self._pick()
        try:
            return getattr(backend, method)(*args)
        except BinanceError as exc:
            if backend is self._demo:
                raise
            logger.warning("Binance %s failed (%s); flipping to demo", method, exc)
            self._backend = "demo"
            return getattr(self._demo, method)(*args)
