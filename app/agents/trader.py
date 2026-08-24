"""Trader — turns the research plan into a Buy / Hold / Sell ticket."""

from __future__ import annotations

from app.models import AgentReport, Indicators, rating_to_action


def trader_agent(plan: AgentReport, ind: Indicators) -> AgentReport:
    action = rating_to_action(plan.stance if plan.stance in
                              {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
                              else "Hold")
    # If the plan is a mild lean, the trader can sit out when ATR is stretched.
    if plan.stance in {"Overweight", "Underweight"} and ind.atr_pct > 5:
        action = "Hold"
    stop = None
    take = None
    if action == "Buy":
        stop = ind.last_close - 1.6 * ind.atr
        take = ind.last_close + 2.4 * ind.atr
    elif action == "Sell":
        stop = ind.last_close + 1.6 * ind.atr
        take = ind.last_close - 2.4 * ind.atr
    return AgentReport(
        name="Trader",
        role="trader",
        stance=action,
        score=plan.score,
        confidence=plan.confidence,
        summary=f"FINAL TRANSACTION PROPOSAL: **{action.upper()}**",
        details=(
            f"Action {action} at {ind.last_close:.6g}. Stop {stop:.6g}."
            if stop is not None
            else f"Action {action} — no ticket this round."
        ),
        signals=[
            {"name": "entry", "value": ind.last_close, "read": "last"},
            {"name": "stop", "value": stop, "read": "1.6 ATR"},
            {"name": "target", "value": take, "read": "2.4 ATR"},
        ],
    )
