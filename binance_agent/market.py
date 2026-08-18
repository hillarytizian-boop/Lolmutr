from __future__ import annotations

import hashlib
import hmac
import logging
import math
import time
from datetime import UTC, datetime
from statistics import pstdev
from urllib.parse import urlencode

import httpx

from .models import Candle, MarketSnapshot

logger = logging.getLogger(__name__)


class BinanceAPIError(RuntimeError):
    """A sanitized Binance API error safe to return to clients."""


def sma(values: list[float], period: int) -> float:
    if not values:
        return 0
    window = values[-period:]
    return sum(window) / len(window)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0
    multiplier = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * multiplier + result * (1 - multiplier)
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < 2:
        return 50
    changes = [
        current - previous
        for previous, current in zip(values, values[1:], strict=False)
    ]
    window = changes[-period:]
    gains = sum(max(change, 0) for change in window) / len(window)
    losses = sum(max(-change, 0) for change in window) / len(window)
    if losses == 0:
        return 100 if gains else 50
    relative_strength = gains / losses
    return 100 - 100 / (1 + relative_strength)


def realized_volatility(values: list[float]) -> float:
    if len(values) < 3:
        return 0
    returns = [
        math.log(current / previous)
        for previous, current in zip(values, values[1:], strict=False)
        if previous > 0 and current > 0
    ]
    return pstdev(returns) * math.sqrt(24) * 100 if len(returns) > 1 else 0


class MarketDataClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        *,
        allow_synthetic: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.allow_synthetic = allow_synthetic
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(15.0, connect=8.0),
            headers={"User-Agent": "BinanceTradingAgent/0.1"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BinanceAPIError("Binance is temporarily unreachable") from exc
        if response.is_error:
            try:
                payload = response.json()
                message = payload.get("msg", "request rejected")
                code = payload.get("code", response.status_code)
            except (ValueError, AttributeError):
                message = "request rejected"
                code = response.status_code
            raise BinanceAPIError(f"Binance error {code}: {message}")
        return response.json()

    async def snapshot(self, symbol: str, interval: str = "1h", limit: int = 100) -> MarketSnapshot:
        try:
            ticker, raw_klines = await self._gather_market(symbol, interval, limit)
            return self._build_snapshot(symbol, ticker, raw_klines)
        except BinanceAPIError:
            if not self.allow_synthetic:
                raise
            logger.warning("Using synthetic market data for %s because Binance is unavailable", symbol)
            return self._synthetic_snapshot(symbol, limit)

    async def _gather_market(self, symbol: str, interval: str, limit: int):
        import asyncio

        return await asyncio.gather(
            self._request("GET", "/api/v3/ticker/24hr", params={"symbol": symbol}),
            self._request(
                "GET",
                "/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            ),
        )

    @staticmethod
    def _build_snapshot(symbol: str, ticker: dict, raw_klines: list[list]) -> MarketSnapshot:
        candles = [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in raw_klines
        ]
        closes = [candle.close for candle in candles]
        return MarketSnapshot(
            symbol=symbol,
            price=float(ticker["lastPrice"]),
            change_24h_pct=float(ticker["priceChangePercent"]),
            high_24h=float(ticker["highPrice"]),
            low_24h=float(ticker["lowPrice"]),
            volume_24h=float(ticker["volume"]),
            quote_volume_24h=float(ticker["quoteVolume"]),
            rsi_14=rsi(closes),
            sma_20=sma(closes, 20),
            sma_50=sma(closes, 50),
            ema_12=ema(closes, 12),
            ema_26=ema(closes, 26),
            volatility_pct=realized_volatility(closes),
            data_source="binance",
            updated_at=datetime.now(UTC),
            candles=candles,
        )

    @staticmethod
    def _synthetic_snapshot(symbol: str, limit: int) -> MarketSnapshot:
        anchors = {"BTCUSDT": 64_280.0, "ETHUSDT": 3_420.0, "SOLUSDT": 172.4}
        anchor = anchors.get(symbol, 100.0)
        seed = sum(ord(char) for char in symbol)
        hour = int(time.time() // 3600)
        candles: list[Candle] = []
        for index in range(limit):
            phase = (hour - limit + index + seed) / 8
            trend = 1 + (index - limit) * 0.00028
            close = anchor * trend * (1 + math.sin(phase) * 0.008 + math.sin(phase / 3) * 0.004)
            open_price = close * (1 - math.sin(phase + 0.7) * 0.0018)
            candles.append(
                Candle(
                    open_time=(hour - limit + index) * 3_600_000,
                    open=open_price,
                    high=max(open_price, close) * 1.0025,
                    low=min(open_price, close) * 0.9975,
                    close=close,
                    volume=1000 + abs(math.sin(phase)) * 2800,
                )
            )
        closes = [item.close for item in candles]
        current = closes[-1]
        change = (current / closes[-25] - 1) * 100
        return MarketSnapshot(
            symbol=symbol,
            price=current,
            change_24h_pct=change,
            high_24h=max(item.high for item in candles[-24:]),
            low_24h=min(item.low for item in candles[-24:]),
            volume_24h=sum(item.volume for item in candles[-24:]),
            quote_volume_24h=sum(item.volume * item.close for item in candles[-24:]),
            rsi_14=rsi(closes),
            sma_20=sma(closes, 20),
            sma_50=sma(closes, 50),
            ema_12=ema(closes, 12),
            ema_26=ema(closes, 26),
            volatility_pct=realized_volatility(closes),
            data_source="synthetic",
            updated_at=datetime.now(UTC),
            candles=candles,
        )

    async def symbol_filters(self, symbol: str) -> dict[str, float]:
        payload = await self._request("GET", "/api/v3/exchangeInfo", params={"symbol": symbol})
        symbols = payload.get("symbols", [])
        if not symbols:
            raise BinanceAPIError(f"Unknown Binance symbol: {symbol}")
        filters = {item["filterType"]: item for item in symbols[0].get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
        return {
            "step_size": float(lot.get("stepSize", 0.00000001)),
            "min_qty": float(lot.get("minQty", 0)),
            "max_qty": float(lot.get("maxQty", 1e30)),
            "min_notional": float(notional.get("minNotional", 0)),
        }

    async def signed_request(self, method: str, path: str, params: dict | None = None):
        if not self.api_key or not self.api_secret:
            raise BinanceAPIError("Binance credentials are not configured")
        values = dict(params or {})
        values["timestamp"] = int(time.time() * 1000)
        values["recvWindow"] = 5000
        query = urlencode(values, doseq=True)
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        headers = {"X-MBX-APIKEY": self.api_key}
        return await self._request(
            method,
            path,
            params={**values, "signature": signature},
            headers=headers,
        )
