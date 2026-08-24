"""Bull / bear research debate and the Research Manager synthesis."""

from __future__ import annotations

from app.models import AgentReport


def bull_researcher(reports: list[AgentReport], symbol: str, price: float) -> AgentReport:
    bulls = [r for r in reports if r.score > 0]
    strength = sum(max(r.score, 0) for r in reports) / max(len(reports), 1)
    points = [f"{r.name}: {r.summary}" for r in bulls] or [
        "No analyst is outright long; the bull case is mean-reversion from stretched sellers."
    ]
    return AgentReport(
        name="Bull Researcher",
        role="debate",
        stance="Bullish",
        score=round(min(1.0, strength + 0.15), 3),
        confidence="medium",
        summary=f"Constructive case for {symbol} at {price:.6g}.",
        details=" ".join(points),
        signals=[{"name": r.name, "value": r.score, "read": r.stance} for r in reports],
    )


def bear_researcher(reports: list[AgentReport], symbol: str, price: float) -> AgentReport:
    bears = [r for r in reports if r.score < 0]
    strength = sum(max(-r.score, 0) for r in reports) / max(len(reports), 1)
    points = [f"{r.name}: {r.summary}" for r in bears] or [
        "No analyst is outright short; the bear case is fade-the-rip after a crowded bid."
    ]
    return AgentReport(
        name="Bear Researcher",
        role="debate",
        stance="Bearish",
        score=round(max(-1.0, -strength - 0.15), 3),
        confidence="medium",
        summary=f"Cautious case against chasing {symbol} at {price:.6g}.",
        details=" ".join(points),
        signals=[{"name": r.name, "value": r.score, "read": r.stance} for r in reports],
    )


def research_manager(
    analysts: list[AgentReport],
    bull: AgentReport,
    bear: AgentReport,
) -> AgentReport:
    avg = sum(r.score for r in analysts) / max(len(analysts), 1)
    # Debate slightly pulls the average toward the stronger rhetorician.
    tilt = (bull.score + bear.score) * 0.15
    score = max(-1.0, min(1.0, avg + tilt))
    if score >= 0.45:
        rec = "Buy"
    elif score >= 0.18:
        rec = "Overweight"
    elif score <= -0.45:
        rec = "Sell"
    elif score <= -0.18:
        rec = "Underweight"
    else:
        rec = "Hold"
    return AgentReport(
        name="Research Manager",
        role="plan",
        stance=rec,
        score=round(score, 3),
        confidence="high" if abs(score) > 0.4 else "medium",
        summary=f"Investment plan: {rec} (composite {score:+.2f}).",
        details=(
            f"Bull: {bull.summary} Bear: {bear.summary} "
            f"The desk sides with the {'bull' if score >= 0 else 'bear'} "
            f"after weighting technicals, sentiment, news, and book structure."
        ),
        signals=[{"name": "recommendation", "value": rec, "read": "5-tier"}],
    )
