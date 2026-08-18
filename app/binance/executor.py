"""Turn a Portfolio Manager rating into an order, with hard safety rails."""

from __future__ import annotations

from typing import Any

from app.binance.client import BinanceError, BinancePublic, BinanceSigned
from app.binance.paper import PaperBroker
from app.binance.symbols import to_binance
from app.config import get_settings
from app.models import rating_to_action


class ExecutionError(RuntimeError):
    pass


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
                return None
            return broker.market_order(
                pair, "BUY", notional=notional, price=price, reason=reason
            )
        position = next((p for p in snap["positions"] if p["symbol"] == pair), None)
        if not position or position["qty"] <= 0:
            return None
        return broker.market_order(
            pair, "SELL", quantity=position["qty"], price=price, reason=reason
        )

    # testnet / unlocked live
    try:
        signed = BinanceSigned()
        public = BinancePublic()
        mark = public.price(pair)
        if action == "Buy":
            # Size against free USDT on the signed account.
            account = signed.account()
            usdt = 0.0
            for bal in account.get("balances", []):
                if bal.get("asset") == "USDT":
                    usdt = float(bal.get("free") or 0)
                    break
            notional = usdt * max(0.0, size_pct)
            qty = notional / mark if mark else 0.0
            from app.binance.client import quantize_qty

            qty = quantize_qty(pair, qty, price=mark)
            if qty <= 0:
                return None
            raw = signed.market_order(pair, "BUY", qty)
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
        return {
            "id": str(raw.get("orderId")),
            "ts": str(raw.get("transactTime")),
            "symbol": pair,
            "side": raw.get("side"),
            "qty": float(raw.get("executedQty") or 0),
            "price": mark,
            "status": raw.get("status"),
            "venue": settings.trading_mode,
            "reason": reason,
            "raw_status": raw.get("status"),
        }
    except BinanceError as exc:
        raise ExecutionError(str(exc)) from exc
