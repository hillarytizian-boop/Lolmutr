"""Binance REST helpers.

Public market data never needs a key. Signed endpoints are used only when
the operator opts into testnet or (with an extra confirm) live trading.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.binance.symbols import to_binance
from app.config import get_settings
from app.models import Candle

_TIMEOUT = 15.0


class BinanceError(RuntimeError):
    pass


def _get(base: str, path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{base}{path}"
    try:
        response = httpx.get(url, params=params, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise BinanceError(f"Binance request failed: {exc}") from exc
    if response.status_code >= 400:
        raise BinanceError(f"Binance {response.status_code}: {response.text[:300]}")
    return response.json()


class BinancePublic:
    def __init__(self, base: str | None = None) -> None:
        self.base = (base or get_settings().public_rest).rstrip("/")

    def ping(self) -> bool:
        _get(self.base, "/api/v3/ping")
        return True

    def ticker(self, symbol: str) -> dict[str, Any]:
        pair = to_binance(symbol)
        data = _get(self.base, "/api/v3/ticker/24hr", {"symbol": pair})
        return _shape_ticker(data)

    def tickers(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        data = _get(self.base, "/api/v3/ticker/24hr")
        wanted = {to_binance(s) for s in symbols} if symbols else None
        out = []
        for row in data:
            if not row.get("symbol", "").endswith("USDT"):
                continue
            if wanted is not None and row["symbol"] not in wanted:
                continue
            out.append(_shape_ticker(row))
        out.sort(key=lambda r: r["quote_volume"], reverse=True)
        return out

    def klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]:
        pair = to_binance(symbol)
        raw = _get(
            self.base,
            "/api/v3/klines",
            {"symbol": pair, "interval": interval, "limit": limit},
        )
        return [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=int(row[6]),
            )
            for row in raw
        ]

    def depth(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        pair = to_binance(symbol)
        data = _get(self.base, "/api/v3/depth", {"symbol": pair, "limit": limit})
        return {
            "symbol": pair,
            "last_update_id": data.get("lastUpdateId"),
            "bids": [[float(p), float(q)] for p, q in data.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q in data.get("asks", [])],
        }

    def price(self, symbol: str) -> float:
        pair = to_binance(symbol)
        data = _get(self.base, "/api/v3/ticker/price", {"symbol": pair})
        return float(data["price"])


class BinanceSigned:
    """HMAC-signed client for testnet / live spot. Paper mode never uses this."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.signed_ready:
            raise BinanceError(
                "signed Binance client is locked. Use paper mode, or set "
                "BINANCE_API_KEY / BINANCE_API_SECRET (and BINANCE_LIVE_CONFIRM="
                "I_UNDERSTAND for live)."
            )
        self.base = settings.binance_rest.rstrip("/")
        self.key = settings.binance_api_key
        self.secret = settings.binance_api_secret.encode("utf-8")

    def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
        payload = dict(params)
        payload["timestamp"] = int(time.time() * 1000)
        payload["recvWindow"] = 5000
        query = urlencode(payload, doseq=True)
        signature = hmac.new(self.secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.key}
        try:
            response = httpx.request(method, url, headers=headers, timeout=_TIMEOUT)
        except httpx.HTTPError as exc:
            raise BinanceError(f"Binance signed request failed: {exc}") from exc
        if response.status_code >= 400:
            raise BinanceError(f"Binance {response.status_code}: {response.text[:300]}")
        return response.json()

    def account(self) -> dict[str, Any]:
        return self._signed("GET", "/api/v3/account", {})

    def market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        pair = to_binance(symbol)
        side_u = side.upper()
        if side_u not in {"BUY", "SELL"}:
            raise BinanceError("side must be BUY or SELL")
        if quantity <= 0:
            raise BinanceError("quantity must be positive")
        return self._signed(
            "POST",
            "/api/v3/order",
            {
                "symbol": pair,
                "side": side_u,
                "type": "MARKET",
                "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
                "newOrderRespType": "FULL",
            },
        )


def _shape_ticker(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "price": float(row.get("lastPrice") or row.get("price") or 0),
        "change": float(row.get("priceChange") or 0),
        "change_pct": float(row.get("priceChangePercent") or 0),
        "high": float(row.get("highPrice") or 0),
        "low": float(row.get("lowPrice") or 0),
        "volume": float(row.get("volume") or 0),
        "quote_volume": float(row.get("quoteVolume") or 0),
        "trades": int(row.get("count") or 0),
    }
