"""Analyst team — the same four desks as TradingAgents, crypto-adapted.

Fundamentals is dropped for spot crypto (TradingAgents does the same) and
replaced by a market-structure / flow read so the firm still has four voices.
"""

from __future__ import annotations

from typing import Any

from app.models import AgentReport, Indicators


def _conf(score_abs: float) -> str:
    if score_abs >= 0.45:
        return "high"
    if score_abs >= 0.2:
        return "medium"
    return "low"


def _stance(score: float) -> str:
    if score >= 0.25:
        return "Bullish"
    if score <= -0.25:
        return "Bearish"
    return "Neutral"


def market_analyst(symbol: str, ind: Indicators) -> AgentReport:
    signals: list[dict[str, Any]] = []
    score = 0.0

    if ind.rsi < 30:
        score += 0.38
        signals.append({"name": "RSI", "value": round(ind.rsi, 2), "read": "oversold"})
    elif ind.rsi > 70:
        score -= 0.38
        signals.append({"name": "RSI", "value": round(ind.rsi, 2), "read": "overbought"})
    else:
        score += (50.0 - ind.rsi) / 50.0 * 0.16
        signals.append({"name": "RSI", "value": round(ind.rsi, 2), "read": "mid-range"})

    if ind.macd_hist > 0:
        score += 0.22 if ind.macd > ind.macd_signal else 0.10
        signals.append(
            {"name": "MACD", "value": round(ind.macd_hist, 6), "read": "positive histogram"}
        )
    else:
        score -= 0.22 if ind.macd < ind.macd_signal else 0.10
        signals.append(
            {"name": "MACD", "value": round(ind.macd_hist, 6), "read": "negative histogram"}
        )

    if ind.last_close > ind.ema20 > ind.ema50:
        score += 0.20
        signals.append({"name": "EMA stack", "value": ind.ema20, "read": "bullish alignment"})
    elif ind.last_close < ind.ema20 < ind.ema50:
        score -= 0.20
        signals.append({"name": "EMA stack", "value": ind.ema20, "read": "bearish alignment"})
    else:
        signals.append({"name": "EMA stack", "value": ind.ema20, "read": "mixed"})

    bb_width = max(ind.bb_upper - ind.bb_lower, 1e-9)
    bb_pos = (ind.last_close - ind.bb_lower) / bb_width
    if bb_pos < 0.15:
        score += 0.14
        signals.append({"name": "Bollinger", "value": round(bb_pos, 3), "read": "near lower band"})
    elif bb_pos > 0.85:
        score -= 0.14
        signals.append({"name": "Bollinger", "value": round(bb_pos, 3), "read": "near upper band"})
    else:
        signals.append({"name": "Bollinger", "value": round(bb_pos, 3), "read": "inside bands"})

    if ind.volume_sma > 0 and ind.volume > 1.4 * ind.volume_sma:
        score += 0.08 if ind.change_24h >= 0 else -0.08
        signals.append({"name": "Volume", "value": ind.volume, "read": "expanding"})

    if ind.last_close >= ind.high_20:
        score += 0.08
        signals.append({"name": "Range", "value": ind.high_20, "read": "20-bar high break"})
    elif ind.last_close <= ind.low_20:
        score -= 0.08
        signals.append({"name": "Range", "value": ind.low_20, "read": "20-bar low break"})

    score = max(-1.0, min(1.0, score))
    details = (
        f"{symbol} last {ind.last_close:.6g} ({ind.change_24h:+.2f}% 24h). "
        f"RSI {ind.rsi:.1f}, MACD hist {ind.macd_hist:.6g}, "
        f"EMA20 {ind.ema20:.6g} / EMA50 {ind.ema50:.6g}, "
        f"ATR {ind.atr_pct:.2f}% of spot. "
        f"Stoch %K {ind.stoch_k:.1f}."
    )
    return AgentReport(
        name="Market Analyst",
        role="technicals",
        stance=_stance(score),
        score=round(score, 3),
        confidence=_conf(abs(score)),
        summary=(
            f"Technical book is {_stance(score).lower()} with RSI {ind.rsi:.0f} "
            f"and a {'rising' if ind.macd_hist > 0 else 'fading'} MACD histogram."
        ),
        details=details,
        signals=signals,
    )


def sentiment_analyst(
    symbol: str,
    fear_greed: dict[str, Any] | None,
    headlines: list[dict[str, Any]],
) -> AgentReport:
    score = 0.0
    signals: list[dict[str, Any]] = []
    fg_value = None
    if fear_greed and fear_greed.get("value") is not None:
        fg_value = float(fear_greed["value"])
        if fg_value <= 25:
            score += 0.36
            read = "extreme fear (contrarian bid)"
        elif fg_value <= 45:
            score += 0.16
            read = "fear"
        elif fg_value < 55:
            read = "neutral"
        elif fg_value < 75:
            score -= 0.16
            read = "greed"
        else:
            score -= 0.36
            read = "extreme greed (contrarian fade)"
        signals.append({"name": "Fear & Greed", "value": fg_value, "read": read})

    bull, bear = _headline_tone(headlines, symbol)
    net = bull - bear
    if bull + bear:
        score += max(-0.3, min(0.3, net * 0.08))
        signals.append(
            {
                "name": "Headline tone",
                "value": net,
                "read": f"{bull} bullish / {bear} bearish keywords",
            }
        )

    score = max(-1.0, min(1.0, score))
    fg_txt = f"Fear & Greed at {fg_value:.0f}" if fg_value is not None else "Fear & Greed unavailable"
    return AgentReport(
        name="Sentiment Analyst",
        role="sentiment",
        stance=_stance(score),
        score=round(score, 3),
        confidence=_conf(abs(score)) if fg_value is not None else "low",
        summary=f"{fg_txt}; social/news tone nets {bull - bear:+d}.",
        details=(
            "Crypto-adapted sentiment desk (TradingAgents social analyst analogue). "
            f"{fg_txt}. Scanned {len(headlines)} headlines for {symbol}."
        ),
        signals=signals,
    )


def news_analyst(symbol: str, headlines: list[dict[str, Any]]) -> AgentReport:
    bull, bear = _headline_tone(headlines, symbol)
    score = 0.0
    if headlines:
        score = max(-1.0, min(1.0, (bull - bear) / max(4.0, len(headlines) * 0.4)))
    top = headlines[:5]
    lines = [f"- {item.get('title') or ''}" for item in top]
    details = "\n".join(lines) if lines else "No recent headlines available from public crypto wires."
    return AgentReport(
        name="News Analyst",
        role="news",
        stance=_stance(score),
        score=round(score, 3),
        confidence="medium" if headlines else "low",
        summary=(
            f"{len(headlines)} headlines scored {bull} risk-on vs {bear} risk-off."
            if headlines
            else "News wire was empty; no incremental catalyst."
        ),
        details=details,
        signals=[
            {"name": "Bullish keywords", "value": bull, "read": "count"},
            {"name": "Bearish keywords", "value": bear, "read": "count"},
        ],
    )


def structure_analyst(symbol: str, ind: Indicators, depth: dict[str, Any] | None) -> AgentReport:
    """Crypto stand-in for the fundamentals desk: book, range, realized vol."""
    score = 0.0
    signals: list[dict[str, Any]] = []

    if depth and depth.get("bids") and depth.get("asks"):
        bid_notional = sum(p * q for p, q in depth["bids"][:10])
        ask_notional = sum(p * q for p, q in depth["asks"][:10])
        total = bid_notional + ask_notional
        imb = (bid_notional - ask_notional) / total if total else 0.0
        score += max(-0.3, min(0.3, imb))
        signals.append({"name": "Book imbalance", "value": round(imb, 3), "read": "top-10 notional"})
        spread = depth["asks"][0][0] - depth["bids"][0][0]
        spread_bps = (spread / depth["bids"][0][0] * 10_000) if depth["bids"][0][0] else 0
        signals.append({"name": "Spread", "value": round(spread_bps, 2), "read": "bps"})
        if spread_bps > 8:
            score -= 0.08

    if ind.atr_pct > 4:
        score *= 0.7
        signals.append({"name": "ATR", "value": round(ind.atr_pct, 2), "read": "elevated vol"})
    else:
        signals.append({"name": "ATR", "value": round(ind.atr_pct, 2), "read": "contained vol"})

    mid = (ind.high_20 + ind.low_20) / 2 if ind.high_20 else ind.last_close
    loc = (ind.last_close - mid) / max(ind.high_20 - ind.low_20, 1e-9)
    score += max(-0.15, min(0.15, loc))
    score = max(-1.0, min(1.0, score))

    return AgentReport(
        name="Market Structure",
        role="structure",
        stance=_stance(score),
        score=round(score, 3),
        confidence=_conf(abs(score)),
        summary=f"Book and range location for {symbol} lean {_stance(score).lower()}.",
        details=(
            f"ATR {ind.atr_pct:.2f}% of spot. 20-bar range "
            f"{ind.low_20:.6g}–{ind.high_20:.6g}. "
            "This desk replaces equity fundamentals for crypto pairs."
        ),
        signals=signals,
    )


_BULL = {
    "surge",
    "rally",
    "breakout",
    "adoption",
    "etf",
    "inflow",
    "inflows",
    "bullish",
    "ath",
    "upgrade",
    "record",
    "approval",
    "partnership",
    "accumulate",
    "halving",
}
_BEAR = {
    "crash",
    "dump",
    "hack",
    "lawsuit",
    "ban",
    "outflow",
    "outflows",
    "bearish",
    "liquidation",
    "exploit",
    "sec",
    "fraud",
    "default",
    "collapse",
    "probe",
}


def _headline_tone(headlines: list[dict[str, Any]], symbol: str) -> tuple[int, int]:
    bull = bear = 0
    for item in headlines:
        text = f"{item.get('title', '')} {item.get('body', '')}".lower()
        words = set(text.replace(":", " ").replace(",", " ").split())
        bull += len(words & _BULL)
        bear += len(words & _BEAR)
    return bull, bear
