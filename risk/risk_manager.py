"""Deterministic SL/TP when TradingAgents did not emit levels. Labeled as system."""

from __future__ import annotations

from brain.decision import TradeDecision
from market.market_data import SymbolSnapshot


def attach_system_levels(decision: TradeDecision, snap: SymbolSnapshot | None) -> TradeDecision:
    if snap is None or snap.price <= 0 or snap.atr <= 0:
        return decision
    if decision.entry is None:
        decision.entry = snap.price
    if decision.action == "BUY":
        if decision.stop_loss is None:
            decision.stop_loss = snap.price - 1.6 * snap.atr
            decision.risk_source = "system"
        if not decision.take_profit:
            decision.take_profit = [snap.price + 2.4 * snap.atr]
            decision.risk_source = "system"
    elif decision.action == "SELL":
        if decision.stop_loss is None:
            decision.stop_loss = snap.price + 1.6 * snap.atr
            decision.risk_source = "system"
        if not decision.take_profit:
            decision.take_profit = [snap.price - 2.4 * snap.atr]
            decision.risk_source = "system"
    if decision.stop_loss and decision.entry and decision.take_profit:
        risk = abs(decision.entry - decision.stop_loss)
        reward = abs(decision.take_profit[0] - decision.entry)
        if risk > 0:
            decision.risk_reward = round(reward / risk, 2)
    return decision
