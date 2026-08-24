"""Deterministic SL/TP and position sizing. Not an AI."""

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


def size_position(
    *,
    equity: float,
    cash: float,
    price: float,
    stop: float | None,
    risk_per_trade: float,
    max_position_percent: float,
    min_notional: float,
) -> tuple[float, float, str | None]:
    """Return (qty, notional, block_reason). Never sizes 100% of the account."""
    if equity <= 0 or cash <= 0 or price <= 0:
        return 0.0, 0.0, "insufficient balance"
    cap_pct = min(0.90, max(0.01, float(max_position_percent)))
    cap = min(cash * 0.98, equity * cap_pct)
    stop_dist = abs(price - stop) if stop and stop > 0 else price * 0.02
    if stop_dist <= 0:
        return 0.0, 0.0, "invalid stop-loss distance"
    risk_usd = max(0.0, equity * max(0.0, risk_per_trade))
    qty = risk_usd / stop_dist if stop_dist else 0.0
    notional = qty * price
    if notional > cap:
        qty = cap / price
        notional = cap
    floor = max(1.0, float(min_notional))
    if notional + 1e-9 < floor:
        if cap + 1e-9 >= floor:
            # Smallest valid exchange ticket, still under the cap — never 100%.
            notional = min(cap, floor)
            qty = notional / price
        else:
            return 0.0, 0.0, (
                f"BELOW EXCHANGE MINIMUM Required: ${floor:.2f} Available: ${notional:.2f}"
            )
    return qty, notional, None
