"""Technical indicators computed from Binance klines.

Pure Python so the desk stays lean. Formulas match the common Wilder / EMA
conventions a TradingAgents market analyst would read off a chart.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.models import Candle, Indicators


def _closes(candles: Sequence[Candle]) -> list[float]:
    return [c.close for c in candles]


def sma(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        raise ValueError(f"need {period} values for SMA, got {len(values)}")
    window = values[-period:]
    return sum(window) / period


def ema(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        raise ValueError(f"need {period} values for EMA, got {len(values)}")
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    current = seed
    for price in values[period:]:
        current = price * k + current * (1.0 - k)
    return current


def ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"need {period} values for EMA, got {len(values)}")
    k = 2.0 / (period + 1)
    out: list[float] = []
    current = sum(values[:period]) / period
    for _ in values[: period - 1]:
        out.append(float("nan"))
    out.append(current)
    for price in values[period:]:
        current = price * k + current * (1.0 - k)
        out.append(current)
    return out


def stdev(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def rsi(values: Sequence[float], period: int = 14) -> float:
    if len(values) < period + 1:
        raise ValueError(f"need {period + 1} values for RSI, got {len(values)}")
    gains: list[float] = []
    losses: list[float] = []
    for prev, curr in zip(values[:-1], values[1:]):
        delta = curr - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float]:
    if len(values) < slow + signal:
        raise ValueError("not enough values for MACD")
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    macd_line: list[float] = []
    for f, s in zip(fast_series, slow_series):
        if math.isnan(f) or math.isnan(s):
            continue
        macd_line.append(f - s)
    if len(macd_line) < signal:
        raise ValueError("not enough MACD points for signal")
    signal_line = ema(macd_line, signal)
    last = macd_line[-1]
    return last, signal_line, last - signal_line


def atr(candles: Sequence[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        raise ValueError("not enough candles for ATR")
    trs: list[float] = []
    for prev, curr in zip(candles[:-1], candles[1:]):
        trs.append(
            max(
                curr.high - curr.low,
                abs(curr.high - prev.close),
                abs(curr.low - prev.close),
            )
        )
    current = sum(trs[:period]) / period
    for value in trs[period:]:
        current = (current * (period - 1) + value) / period
    return current


def stochastic(candles: Sequence[Candle], period: int = 14) -> float:
    window = candles[-period:]
    highest = max(c.high for c in window)
    lowest = min(c.low for c in window)
    if highest == lowest:
        return 50.0
    return 100.0 * (window[-1].close - lowest) / (highest - lowest)


def compute_indicators(candles: Sequence[Candle], change_24h: float = 0.0) -> Indicators:
    if len(candles) < 60:
        raise ValueError("need at least 60 candles for a full indicator set")
    closes = _closes(candles)
    last = closes[-1]
    macd_val, signal, hist = macd(closes)
    sma20 = sma(closes, 20)
    deviation = stdev(closes[-20:])
    atr_val = atr(candles, 14)
    volume = candles[-1].volume
    volume_sma = sum(c.volume for c in candles[-20:]) / 20.0
    return Indicators(
        last_close=last,
        change_24h=change_24h,
        rsi=rsi(closes, 14),
        macd=macd_val,
        macd_signal=signal,
        macd_hist=hist,
        ema20=ema(closes, 20),
        ema50=ema(closes, 50),
        sma20=sma20,
        bb_upper=sma20 + 2 * deviation,
        bb_middle=sma20,
        bb_lower=sma20 - 2 * deviation,
        atr=atr_val,
        atr_pct=(atr_val / last * 100.0) if last else 0.0,
        volume=volume,
        volume_sma=volume_sma,
        high_20=max(c.high for c in candles[-20:]),
        low_20=min(c.low for c in candles[-20:]),
        stoch_k=stochastic(candles, 14),
    )
