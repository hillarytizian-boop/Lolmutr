"""Cockpit loop: eyes → TradingAgents brain → deterministic gate → hands."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from app.binance.executor import ExecutionError, execute_decision
from app.binance.paper import PaperBroker
from app.binance.symbols import to_binance
from app.config import HALT_FILE, get_settings
from app.logging_setup import setup_logging
from brain.decision import TradeDecision
from brain.tradingagents_brain import TradingAgentsBrain, brain_status
from dashboard.terminal import CockpitUI
from market.market_data import CryptoMarketAdapter
from risk.execution_gate import execution_gate
from risk.risk_manager import attach_system_levels
from storage.state import CockpitState, load_state, save_state, utc_day

logger = logging.getLogger("trading")


def _cycle_id(symbol: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{to_binance(symbol)}"


def _marks(broker: PaperBroker, market: CryptoMarketAdapter) -> dict[str, float]:
    snap = broker.snapshot()
    out: dict[str, float] = {}
    for pos in snap["positions"]:
        try:
            out[pos["symbol"]] = market.feed.price(pos["symbol"])
        except Exception:
            continue
    return out


def run_cockpit(*, once: bool = False) -> None:
    setup_logging()
    settings = get_settings()
    if settings.trading_mode == "live" and not settings.live_unlocked:
        logger.error("LIVE is locked. Set BINANCE_LIVE_CONFIRM=I_UNDERSTAND or stay on paper.")
        sys.exit(2)

    market = CryptoMarketAdapter()
    broker = PaperBroker()
    brain = TradingAgentsBrain()
    ui = CockpitUI()
    state = load_state()
    stop = {"flag": False}
    keys = {"cmd": ""}
    view: dict = {"cycle": state.cycle, "watch": [], "health": {}, "account": {}, "stages": {}}

    def _stop(*_a: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def _keys() -> None:
        if not sys.stdin.isatty():
            return
        try:
            import termios
            import tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while not stop["flag"]:
                    ch = sys.stdin.read(1)
                    if ch:
                        keys["cmd"] = ch
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            return

    threading.Thread(target=_keys, daemon=True).start()

    ok, detail = brain.available()
    logger.info("cockpit start brain=%s (%s) mode=%s", "ONLINE" if ok else "OFFLINE", detail, settings.trading_mode)

    last_analyze = 0.0
    while not stop["flag"]:
        cmd = keys.pop("cmd", "") or ""
        if cmd in {"q", "Q"}:
            break
        if cmd in {"p", "P"}:
            state.paused = True
        if cmd in {"r", "R"}:
            state.paused = False
        if HALT_FILE.exists():
            state.halted = True

        today = utc_day()
        if state.day != today:
            state.day = today
            state.start_equity = None
            if not state.goal_hit:
                state.halted = False

        ctx = market.context(list(settings.watchlist), settings.interval)
        snap_acct = broker.snapshot(_marks(broker, market))
        if state.start_equity is None:
            state.start_equity = float(snap_acct["equity"])
        day_pnl = 0.0
        if state.start_equity:
            day_pnl = (float(snap_acct["equity"]) - state.start_equity) / state.start_equity * 100.0

        status = brain_status()
        view["clock"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        view["cycle"] = state.cycle
        view["account"] = {**snap_acct, "day_pnl_pct": day_pnl}
        view["positions"] = snap_acct["positions"]
        view["health"] = {
            "Exchange API": "ONLINE" if ctx.connected else "OFFLINE",
            "Market Data": ctx.feed.upper() if ctx.connected else "OFFLINE",
            "TradingAgents": status["state"],
            "News": ctx.news.status,
            "Sentiment": ctx.sentiment.status if ctx.sentiment else "OFFLINE",
        }
        view["watch"] = [
            {
                "symbol": s.symbol,
                "price": s.price,
                "trend": s.trend,
                "action": ((view.get("decision") or {}).get("action") if (view.get("decision") or {}).get("symbol") == s.symbol else "—"),
                "confidence": (view.get("decision") or {}).get("confidence") or 0,
            }
            for s in ctx.snapshots.values()
        ]

        due = (time.time() - last_analyze) >= settings.loop_seconds or last_analyze == 0
        if due and not state.paused and not state.halted:
            state.cycle += 1
            last_analyze = time.time()
            for symbol in settings.watchlist:
                if stop["flag"] or state.halted:
                    break
                cid = _cycle_id(symbol)
                logger.info("%s TradingAgents analysis started", cid)
                t0 = time.monotonic()

                def on_stage(name: str, status_s: str, _cid=cid) -> None:
                    view.setdefault("stages", {})[name] = status_s

                snap = ctx.snapshots.get(to_binance(symbol))
                blob_parts = [ctx.note]
                if snap:
                    blob_parts.append(
                        f"{snap.symbol} last={snap.price} chg24h={snap.change_pct:+.2f}% "
                        f"RSI={snap.rsi:.1f} ATR%={snap.atr_pct:.2f} trend={snap.trend} "
                        f"EMA20={snap.ema20:.6g} EMA50={snap.ema50:.6g}"
                    )
                if ctx.sentiment and ctx.sentiment.value is not None:
                    blob_parts.append(
                        f"FearGreed={ctx.sentiment.value} ({ctx.sentiment.classification})"
                    )
                else:
                    blob_parts.append("FearGreed=unavailable (not invented)")
                if ctx.news.headlines:
                    blob_parts.append(
                        "Headlines: "
                        + " | ".join(h.get("title", "") for h in ctx.news.headlines[:4])
                    )
                else:
                    blob_parts.append("News wire unavailable (not invented)")
                decision: TradeDecision = brain.analyze(
                    symbol,
                    cycle_id=cid,
                    market_note="\n".join(blob_parts),
                    on_stage=on_stage,
                )
                snap = ctx.snapshots.get(to_binance(symbol))
                if decision.action != "HOLD":
                    attach_system_levels(decision, snap)
                    if settings.small_account:
                        decision.position_size = 0.92
                    elif decision.position_size <= 0:
                        decision.position_size = 0.10

                view["decision"] = decision.to_dict()
                view["stages"] = decision.stages or view.get("stages")
                state.decisions.append(
                    {
                        "cycle_id": cid,
                        "symbol": symbol,
                        "action": decision.action,
                        "rating": decision.rating,
                        "thesis": decision.thesis[:400],
                        "ts": decision.timestamp,
                    }
                )
                save_state(state)

                latency = time.monotonic() - t0
                logger.info(
                    "%s decision=%s rating=%s brain_latency=%.2fs",
                    cid,
                    decision.action,
                    decision.rating,
                    latency,
                )

                gate = execution_gate(
                    decision,
                    snap=snap,
                    equity=float(snap_acct["equity"]),
                    cash=float(snap_acct["cash"]),
                    open_symbols=[p["symbol"] for p in snap_acct["positions"]],
                    last_trade_iso=state.last_trade.get(to_binance(symbol)),
                    start_equity=float(state.start_equity or snap_acct["equity"]),
                    connected=ctx.connected,
                    paused=state.paused,
                    halted=state.halted,
                )
                if not gate.allow:
                    logger.info("%s Execution: SKIPPED %s", cid, gate.blocked_line())
                    continue
                if not settings.auto_execute:
                    logger.info("%s Execution: SKIPPED auto-execute off", cid)
                    continue
                try:
                    order = execute_decision(
                        symbol,
                        decision.rating,
                        float(decision.position_size),
                        float(snap.price if snap else 0),
                        reason=f"TradingAgents {decision.rating} {cid}",
                        broker=broker,
                    )
                except (ExecutionError, ValueError) as exc:
                    logger.error("%s Execution: FAILED %s", cid, exc)
                    continue
                if not order:
                    logger.info("%s Execution: SKIPPED empty fill", cid)
                    continue
                state.last_trade[to_binance(symbol)] = datetime.now(timezone.utc).isoformat()
                save_state(state)
                logger.info("%s Execution: FILLED %s %s", cid, order.get("side"), order.get("qty"))
                snap_acct = broker.snapshot(_marks(broker, market))
            view["cycle"] = state.cycle
            view["account"] = {**snap_acct, "day_pnl_pct": day_pnl}

        if once:
            print(ui._plain(view))
        elif ui.console and ui.rich:
            from rich.live import Live

            if ui.live is None:
                ui.live = Live(ui.render(view), console=ui.console, refresh_per_second=2, screen=False)
                ui.live.start()
            else:
                ui.live.update(ui.render(view))

        if once:
            break
        for _ in range(max(1, min(2, settings.manage_seconds))):
            if stop["flag"]:
                break
            time.sleep(1)

    if ui.live is not None:
        ui.live.stop()
    save_state(state)
    logger.info("cockpit stopped")
