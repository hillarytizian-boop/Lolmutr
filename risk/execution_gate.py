"""Deterministic safety layer. Not an AI. Never upgrades HOLD to BUY."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from brain.decision import TradeDecision
from market.market_data import SymbolSnapshot


@dataclass
class GateResult:
    allow: bool
    reason: str
    code: str

    def blocked_line(self) -> str:
        return f"TRADE BLOCKED reason={self.reason}"


def execution_gate(
    decision: TradeDecision,
    *,
    snap: SymbolSnapshot | None,
    equity: float,
    cash: float,
    open_symbols: list[str],
    last_trade_iso: str | None,
    start_equity: float,
    connected: bool,
    paused: bool,
    halted: bool,
    now: datetime | None = None,
) -> GateResult:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    action = (decision.action or "HOLD").upper()

    if halted:
        return GateResult(False, "emergency stop / halt", "HALT")
    if paused:
        return GateResult(False, "trading paused", "PAUSED")
    if settings.trading_mode == "live" and not settings.live_unlocked:
        return GateResult(False, "live trading locked", "LIVE_LOCKED")
    if action == "HOLD":
        return GateResult(False, "TradingAgents stayed flat", "HOLD")
    if not connected:
        return GateResult(False, "exchange connectivity failed", "NO_EXCHANGE")
    if snap is None or snap.price <= 0:
        return GateResult(False, "missing or invalid market data", "NO_DATA")
    if snap.stale or (time.time() - snap.fetched_at) > 120:
        return GateResult(False, "stale market data", "STALE")
    if start_equity > 0:
        dd = (equity - start_equity) / start_equity * 100.0
        if dd <= -abs(settings.max_daily_loss_pct):
            return GateResult(False, f"daily loss {dd:.2f}% hit circuit breaker", "DAILY_LOSS")
    if action == "BUY":
        if decision.symbol in open_symbols:
            return GateResult(False, "equivalent position already open", "DUPLICATE")
        if len(open_symbols) >= settings.max_positions:
            return GateResult(
                False, f"max concurrent positions {settings.max_positions}", "MAX_POS"
            )
        size_pct = decision.position_size or 0.0
        if size_pct <= 0:
            size_pct = 0.10 if not settings.small_account else 0.92
        notional = equity * size_pct
        floor = max(1.0, float(settings.min_notional))
        if notional + 1e-9 < floor:
            return GateResult(
                False,
                f"POSITION TOO SMALL Required: ${floor:.2f} Available: ${notional:.2f}",
                "TOO_SMALL",
            )
        if cash + 1e-9 < notional:
            return GateResult(False, "insufficient available balance", "NO_CASH")
        if last_trade_iso and settings.cooldown_minutes > 0:
            try:
                last = datetime.fromisoformat(last_trade_iso)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = (now - last).total_seconds() / 60.0
                if age < settings.cooldown_minutes:
                    return GateResult(
                        False,
                        f"cooldown {age:.0f}/{settings.cooldown_minutes}m",
                        "COOLDOWN",
                    )
            except ValueError:
                pass
    if action == "SELL" and decision.symbol not in open_symbols:
        return GateResult(False, "no position to sell", "FLAT")
    if decision.stop_loss is not None and decision.entry:
        if action == "BUY" and decision.stop_loss >= decision.entry:
            return GateResult(False, "stop-loss is not below entry", "BAD_STOP")
        if action == "SELL" and decision.stop_loss <= decision.entry:
            return GateResult(False, "stop-loss is not above entry", "BAD_STOP")
    return GateResult(True, "ok", "OK")
