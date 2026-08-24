"""Turn a Portfolio Manager rating into an order, with hard safety rails."""

from __future__ import annotations

import logging
from typing import Any

from app.binance.client import BinanceError, BinancePublic, BinanceSigned
from app.binance.paper import PaperBroker
from app.binance.symbols import to_binance
from app.config import get_settings
from app.models import rating_to_action

logger = logging.getLogger("trading")


class ExecutionError(RuntimeError):
    pass


def _confirmed(raw: dict[str, Any], mark: float, pair: str, reason: str, venue: str) -> dict[str, Any] | None:
    status = str(raw.get("status") or "").upper()
    qty = float(raw.get("executedQty") or 0)
    if status not in {"FILLED", "PARTIALLY_FILLED"} or qty <= 0:
        logger.error("order not confirmed status=%s qty=%s", status or "unknown", qty)
        return None
    fills = raw.get("fills") or []
    if fills:
        try:
            notion = sum(float(f.get("price") or 0) * float(f.get("qty") or 0) for f in fills)
            qty_sum = sum(float(f.get("qty") or 0) for f in fills)
            if qty_sum > 0:
                mark = notion / qty_sum
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return {
        "id": str(raw.get("orderId") or raw.get("clientOrderId") or ""),
        "ts": str(raw.get("transactTime") or ""),
        "symbol": pair,
        "side": raw.get("side"),
        "qty": qty,
        "price": mark,
        "status": status.lower() if status == "FILLED" else "partial",
        "venue": venue,
        "reason": reason,
        "raw_status": raw.get("status"),
        "client_order_id": raw.get("clientOrderId"),
    }


def _recover_timeout(signed: BinanceSigned, pair: str, client_id: str | None) -> dict[str, Any] | None:
    """Do not resubmit. Ask the exchange whether the original order exists."""
    try:
        if client_id:
            return signed.query_order(pair, client_id=client_id)
    except BinanceError as exc:
        logger.warning("query by client id failed: %s", exc)
    try:
        opens = signed.open_orders(pair)
        if opens:
            return opens[-1]
    except BinanceError as exc:
        logger.warning("openOrders after timeout failed: %s", exc)
    return None


def execute_decision(
    symbol: str,
    rating: str,
    size_pct: float,
    price: float,
    reason: str,
    broker: PaperBroker,
) -> dict[str, Any] | None:
    """Place a paper (default) or signed order for a desk decision.

    Hold / Underweight produce no new long. Sell closes an existing paper
    position. Live trading is refused unless the operator unlocked it.
    Never reports FILLED without a broker/exchange confirmation.
    """
    settings = get_settings()
    pair = to_binance(symbol)
    action = rating_to_action(rating)

    if settings.trading_mode == "live" and not settings.live_unlocked:
        raise ExecutionError(
            "live trading is locked. Stay on paper/testnet, or set "
            "BINANCE_LIVE_CONFIRM=I_UNDERSTAND with valid API keys."
        )

    if action == "Hold":
        return None

    if settings.trading_mode == "paper" or not settings.signed_ready:
        snap = broker.snapshot({pair: price})
        if action == "Buy":
            notional = max(0.0, float(snap["equity"]) * max(0.0, size_pct))
            floor = max(1.0, float(settings.min_notional))
            if notional + 1e-9 < floor:
                raise ExecutionError(
                    f"BELOW EXCHANGE MINIMUM Required: ${floor:.2f} Available: ${notional:.2f}"
                )
            order = broker.market_order(
                pair, "BUY", notional=notional, price=price, reason=reason
            )
            if not order or order.get("status") != "filled":
                raise ExecutionError("paper broker did not confirm fill")
            return order
        position = next((p for p in snap["positions"] if p["symbol"] == pair), None)
        if not position or position["qty"] <= 0:
            return None
        order = broker.market_order(
            pair, "SELL", quantity=position["qty"], price=price, reason=reason
        )
        if not order or order.get("status") != "filled":
            raise ExecutionError("paper broker did not confirm fill")
        return order

    # testnet / unlocked live
    try:
        signed = BinanceSigned()
        public = BinancePublic(base=settings.binance_rest)
        mark = public.price(pair)
        client_id = None
        raw: dict[str, Any] | None = None
        try:
            if action == "Buy":
                account = signed.account()
                usdt = 0.0
                for bal in account.get("balances", []):
                    if bal.get("asset") == "USDT":
                        usdt = float(bal.get("free") or 0)
                        break
                notional = usdt * max(0.0, min(0.90, size_pct))
                qty = notional / mark if mark else 0.0
                from app.binance.client import quantize_qty

                qty = quantize_qty(pair, qty, price=mark)
                if qty <= 0:
                    raise ExecutionError(
                        f"BELOW EXCHANGE MINIMUM Required: ${settings.min_notional:.2f}"
                    )
                raw = signed.market_order(pair, "BUY", qty)
                client_id = raw.get("clientOrderId") if raw else None
            else:
                account = signed.account()
                base = pair.replace("USDT", "").replace("USDC", "")
                free = 0.0
                for bal in account.get("balances", []):
                    if bal.get("asset") == base:
                        free = float(bal.get("free") or 0)
                        break
                if free <= 0:
                    return None
                raw = signed.market_order(pair, "SELL", free)
                client_id = raw.get("clientOrderId") if raw else None
        except BinanceError as exc:
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg:
                recovered = _recover_timeout(signed, pair, client_id)
                if recovered:
                    raw = recovered
                else:
                    raise ExecutionError(
                        f"order submission timed out and exchange has no matching order: {exc}"
                    ) from exc
            else:
                raise
        if not raw:
            return None
        confirmed = _confirmed(raw, mark, pair, reason, settings.trading_mode)
        if not confirmed:
            raise ExecutionError(f"exchange did not confirm fill: {raw.get('status')}")
        return confirmed
    except BinanceError as exc:
        raise ExecutionError(str(exc)) from exc
