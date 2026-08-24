"""Profit capture rules the TradingAgents desk uses after a ticket is live.

The firm still picks the direction. This layer's job is to keep winners and
cut losers: take-profit, hard stop, trailing stop. No promise of profit —
only a mechanical way to realize it when price moves our way.
"""

from __future__ import annotations

from typing import Any


def ratchet_high(high: float, mark: float) -> float:
    return max(float(high), float(mark))


def trailing_stop(high: float, atr: float, trail_mult: float) -> float | None:
    if atr <= 0 or trail_mult <= 0:
        return None
    return float(high) - float(trail_mult) * float(atr)


def effective_stop(
    hard_stop: float | None,
    high: float,
    atr: float,
    trail_mult: float,
) -> float | None:
    trail = trailing_stop(high, atr, trail_mult)
    stops = [s for s in (hard_stop, trail) if s is not None]
    return max(stops) if stops else None


def exit_reason(
    *,
    mark: float,
    take: float | None,
    hard_stop: float | None,
    high: float,
    atr: float,
    trail_mult: float,
) -> str | None:
    """Why a long should be flattened right now, or None to stay in."""
    if take is not None and mark >= take:
        return "take-profit"
    floor = effective_stop(hard_stop, high, atr, trail_mult)
    if floor is None:
        return None
    if mark <= floor:
        trail = trailing_stop(high, atr, trail_mult)
        if (
            trail is not None
            and hard_stop is not None
            and trail > hard_stop
            and mark > hard_stop
        ):
            return "trailing-stop"
        return "stop-loss"
    return None


def profit_size_pct(
    rating: str,
    confidence: float,
    vol_mult: float,
    base_buy: float = 0.12,
    base_over: float = 0.06,
    small_account: bool = False,
) -> float:
    """Conviction-weighted size. A $10 book must commit almost all cash."""
    if rating not in {"Buy", "Overweight"}:
        return 0.0
    if small_account:
        # Min notional on Binance is ~5 USDT. A $10 stake can only run one
        # ticket, so we compound ~90% and leave a fee buffer.
        if rating == "Buy":
            return 0.92 if confidence >= 0.62 else 0.0
        return 0.80 if confidence >= 0.62 else 0.0
    if rating == "Buy":
        raw = base_buy
        if confidence >= 0.75:
            raw *= 1.35
        elif confidence < 0.6:
            raw *= 0.75
    else:
        raw = base_over
    adj = max(0.35, min(1.25, vol_mult))
    return round(min(0.20, raw * adj), 4)


def goal_reached(equity: float, goal_usd: float) -> bool:
    return goal_usd > 0 and equity + 1e-9 >= goal_usd


def too_small_to_trade(equity: float, min_notional: float) -> bool:
    return equity < min_notional


def new_bracket(
    entry: float,
    stop: float | None,
    take: float | None,
    atr: float,
    trail_mult: float,
) -> dict[str, Any]:
    return {
        "entry": float(entry),
        "stop": float(stop) if stop is not None else None,
        "take": float(take) if take is not None else None,
        "high": float(entry),
        "atr": float(atr),
        "trail_mult": float(trail_mult),
    }


def update_bracket(bracket: dict[str, Any], mark: float) -> dict[str, Any]:
    out = dict(bracket)
    out["high"] = ratchet_high(float(out.get("high") or mark), mark)
    return out


def memory_line(trade: dict[str, Any]) -> str:
    pnl = float(trade.get("realized_pnl") or 0)
    sign = "+" if pnl >= 0 else ""
    return (
        f"{trade.get('symbol')} {trade.get('reason')} "
        f"{sign}{pnl:.2f} USDT via {trade.get('engine') or 'desk'}"
    )
