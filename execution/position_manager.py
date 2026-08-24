"""Monitor open positions, simulate / attach SL+TP, flatten when hit."""

from __future__ import annotations

import logging
from typing import Any

from app.binance.client import BinanceError, BinanceSigned
from app.binance.executor import ExecutionError, execute_decision
from app.binance.feed import MarketFeed
from app.binance.indicators import compute_indicators
from app.binance.paper import PaperBroker
from app.config import get_settings
from app.profit import exit_reason, new_bracket, update_bracket

logger = logging.getLogger("trading")


def ensure_bracket(
    state_brackets: dict[str, Any],
    symbol: str,
    entry: float,
    stop: float | None,
    take: float | None,
    atr: float,
    trail_mult: float,
) -> dict[str, Any]:
    existing = state_brackets.get(symbol)
    if existing:
        return existing
    bracket = new_bracket(entry, stop, take, atr, trail_mult)
    state_brackets[symbol] = bracket
    return bracket


def manage_positions(
    *,
    broker: PaperBroker,
    feed: MarketFeed,
    brackets: dict[str, Any],
    auto_execute: bool,
    halted_new: bool,
) -> list[dict[str, Any]]:
    """Check stops/targets. Returns list of flatten events."""
    settings = get_settings()
    if not auto_execute:
        return []
    snap = broker.snapshot()
    events: list[dict[str, Any]] = []
    marks: dict[str, float] = {}
    atrs: dict[str, float] = {}

    live = settings.signed_ready
    live_positions: list[dict[str, Any]] = list(snap["positions"])
    if live:
        try:
            signed = BinanceSigned()
            account = signed.account()
            live_positions = []
            for bal in account.get("balances") or []:
                qty = float(bal.get("free") or 0) + float(bal.get("locked") or 0)
                asset = bal.get("asset") or ""
                if qty <= 0 or asset in {"USDT", "USDC", "BUSD", "FDUSD"}:
                    continue
                symbol = f"{asset}USDT"
                try:
                    px = feed.price(symbol)
                except Exception:
                    continue
                live_positions.append({"symbol": symbol, "qty": qty, "avg_price": px})
        except BinanceError as exc:
            logger.error("cannot list live positions: %s", exc)
            return events

    for pos in live_positions:
        symbol = pos["symbol"]
        try:
            marks[symbol] = feed.price(symbol)
        except Exception as exc:
            logger.warning("mark failed %s: %s", symbol, exc)
            continue
        bracket = brackets.get(symbol) or {}
        atrs[symbol] = float(bracket.get("atr") or 0)
        if atrs[symbol] <= 0:
            try:
                candles = feed.klines(symbol, settings.interval, 80)
                atrs[symbol] = compute_indicators(candles).atr
            except Exception:
                atrs[symbol] = 0.0

    for pos in live_positions:
        symbol = pos["symbol"]
        mark = marks.get(symbol)
        if mark is None:
            continue
        bracket = brackets.get(symbol)
        if not bracket:
            entry = float(pos.get("avg_price") or mark)
            atr = atrs.get(symbol) or entry * 0.01
            take = None if settings.small_account else entry + 2.4 * atr
            bracket = new_bracket(entry, entry - 1.6 * atr, take, atr, settings.trail_atr)
            if settings.signed_ready:
                _try_protect(symbol, float(pos["qty"]), bracket, settings.unprotected_policy)
        bracket = update_bracket(bracket, mark)
        if atrs.get(symbol):
            bracket["atr"] = atrs[symbol]
        brackets[symbol] = bracket
        why = exit_reason(
            mark=mark,
            take=bracket.get("take"),
            hard_stop=bracket.get("stop"),
            high=float(bracket.get("high") or mark),
            atr=float(bracket.get("atr") or 0),
            trail_mult=float(bracket.get("trail_mult") or settings.trail_atr),
        )
        if not why:
            continue
        try:
            order = execute_decision(
                symbol,
                "Sell",
                0.0,
                mark,
                reason=why,
                broker=broker,
            )
        except (ExecutionError, ValueError) as exc:
            logger.error("TRADE REJECTED Reason: %s flatten failed: %s", why, exc)
            continue
        if not order:
            logger.error("flatten %s produced no confirmation", symbol)
            continue
        brackets.pop(symbol, None)
        events.append(
            {
                "symbol": symbol,
                "reason": why,
                "order": order,
                "price": mark,
                "qty": order.get("qty"),
                "realized_pnl": order.get("realized_pnl") or 0,
            }
        )
        logger.info(
            "position closed %s reason=%s qty=%s pnl=%s",
            symbol,
            why,
            order.get("qty"),
            order.get("realized_pnl"),
        )
    return events


def _try_protect(symbol: str, qty: float, bracket: dict[str, Any], policy: str) -> None:
    stop = bracket.get("stop")
    take = bracket.get("take")
    if not stop:
        return
    try:
        signed = BinanceSigned()
        if take:
            signed.oco_order(symbol, "SELL", qty, float(stop), float(take))
            logger.info("protective OCO placed %s stop=%s take=%s", symbol, stop, take)
            return
        # stop-only via stop-limit is exchange-specific; monitor locally
        logger.info("protective OCO skipped (no take) — local monitor %s", symbol)
    except Exception as exc:
        logger.error("protective orders failed %s: %s policy=%s", symbol, exc, policy)
        if policy == "flatten":
            logger.error("UNPROTECTED live position %s — emergency flatten", symbol)
            try:
                signed = BinanceSigned()
                signed.market_order(symbol, "SELL", qty)
            except Exception as flatten_exc:
                logger.error("emergency flatten failed %s: %s", symbol, flatten_exc)


def cancel_entry_orders() -> int:
    settings = get_settings()
    if not settings.signed_ready:
        return 0
    cancelled = 0
    try:
        signed = BinanceSigned()
        for order in signed.open_orders():
            side = str(order.get("side") or "").upper()
            typ = str(order.get("type") or "").upper()
            if side == "BUY" and typ in {"LIMIT", "MARKET", "LIMIT_MAKER"}:
                signed.cancel_order(order["symbol"], order["orderId"])
                cancelled += 1
    except BinanceError as exc:
        logger.error("cancel entry orders failed: %s", exc)
    return cancelled
