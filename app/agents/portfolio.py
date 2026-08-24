"""Portfolio Manager — final 5-tier rating, same vocabulary as TradingAgents."""

from __future__ import annotations

from app.models import AgentReport, Decision, Indicators, rating_size_pct, rating_to_action


def _rating_from_score(score: float) -> str:
    if score >= 0.45:
        return "Buy"
    if score >= 0.18:
        return "Overweight"
    if score <= -0.45:
        return "Sell"
    if score <= -0.18:
        return "Underweight"
    return "Hold"


def portfolio_manager(
    plan: AgentReport,
    trader: AgentReport,
    risk: list[AgentReport],
    ind: Indicators,
    engine: str,
    vol_mult: float,
) -> Decision:
    # PM blends research plan (60%) with the risk-committee average (40%).
    risk_avg = sum(r.score for r in risk) / max(len(risk), 1)
    score = max(-1.0, min(1.0, plan.score * 0.6 + risk_avg * 0.4))
    rating = _rating_from_score(score)
    action = rating_to_action(rating)
    size = rating_size_pct(rating, vol_mult)
    stop = take = None
    if action == "Buy":
        stop = round(ind.last_close - 1.6 * ind.atr, 8)
        take = round(ind.last_close + 2.4 * ind.atr, 8)
    elif action == "Sell":
        stop = round(ind.last_close + 1.6 * ind.atr, 8)
        take = round(ind.last_close - 2.4 * ind.atr, 8)
    confidence = min(0.95, 0.4 + abs(score) * 0.55)
    thesis = (
        f"**Rating**: {rating}\n\n"
        f"**Executive Summary**: {plan.summary} Trader wants {trader.stance}. "
        f"Risk committee average score {risk_avg:+.2f}; vol multiplier {vol_mult:.2f}.\n\n"
        f"**Investment Thesis**: {plan.details}"
    )
    return Decision(
        rating=rating,
        action=action,
        score=round(score, 3),
        confidence=round(confidence, 3),
        size_pct=size,
        entry=ind.last_close,
        stop_loss=stop,
        take_profit=take,
        time_horizon="intraday to 3 days",
        executive_summary=plan.summary,
        thesis=thesis,
        engine=engine,
    )
