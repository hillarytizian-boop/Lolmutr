"""Risk committee — aggressive, conservative, neutral — then a haircut."""

from __future__ import annotations

from app.models import AgentReport, Indicators


def risk_committee(trader: AgentReport, ind: Indicators) -> list[AgentReport]:
    vol = ind.atr_pct
    aggressive = AgentReport(
        name="Aggressive Analyst",
        role="risk",
        stance=trader.stance,
        score=min(1.0, trader.score * 1.15),
        confidence="medium",
        summary="Size up. Crypto trends persist longer than equity mean-reversion assumes.",
        details=f"Would keep the trader's {trader.stance} and add 15% size. ATR {vol:.2f}%.",
        signals=[{"name": "size_mult", "value": 1.15, "read": "aggressive"}],
    )
    conservative = AgentReport(
        name="Conservative Analyst",
        role="risk",
        stance="Hold" if vol > 3.5 and trader.stance != "Hold" else trader.stance,
        score=trader.score * 0.55,
        confidence="high",
        summary="Haircut size. Spot crypto tails are fatter than the ticket implies.",
        details=f"ATR {vol:.2f}% of spot. Prefer half-size or a pass if vol > 3.5%.",
        signals=[{"name": "size_mult", "value": 0.55, "read": "conservative"}],
    )
    neutral = AgentReport(
        name="Neutral Analyst",
        role="risk",
        stance=trader.stance,
        score=trader.score * 0.85,
        confidence="medium",
        summary="Keep the direction, clip the size to a vol-targeted 85%.",
        details="Standard desk policy: trade the signal, never the maximum.",
        signals=[{"name": "size_mult", "value": 0.85, "read": "neutral"}],
    )
    return [aggressive, conservative, neutral]


def risk_multiplier(ind: Indicators) -> float:
    """Map ATR% to a 0.35–1.25 size multiplier."""
    if ind.atr_pct <= 1.2:
        return 1.15
    if ind.atr_pct <= 2.5:
        return 1.0
    if ind.atr_pct <= 4.0:
        return 0.75
    if ind.atr_pct <= 6.0:
        return 0.5
    return 0.35
