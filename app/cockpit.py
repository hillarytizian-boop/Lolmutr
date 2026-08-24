"""Cockpit loop: eyes → TradingAgents brain → deterministic gate → hands."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from app.binance.account import fetch_account
from app.binance.executor import ExecutionError, execute_decision
from app.binance.feed import MarketFeed
from app.binance.paper import PaperBroker
from app.binance.probe import probe as probe_binance
from app.binance.symbols import to_binance
from app.config import HALT_FILE, get_settings, missing_credentials, nvidia_key_present, reload_env
from app.logging_setup import setup_logging, tail_logs
from app.profit import goal_reached
from brain.decision import TradeDecision
from brain.tradingagents_brain import TradingAgentsBrain, brain_status
from dashboard.terminal import CockpitUI
from execution.position_manager import cancel_entry_orders, ensure_bracket, manage_positions
from market.market_data import CryptoMarketAdapter
from risk.execution_gate import execution_gate
from risk.risk_manager import attach_system_levels, size_position
from storage.state import CockpitState, load_state, save_state, trade_id, utc_day

logger = logging.getLogger("trading")


def _cycle_id(symbol: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{to_binance(symbol)}"


def _uptime(started: float) -> str:
    sec = int(max(0, time.time() - started))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _auth_banner(settings, probe: dict) -> tuple[str, str]:
    missing = missing_credentials(settings)
    if settings.trading_mode == "paper":
        if settings.binance_api_key:
            if probe.get("signed_ok"):
                return "OK", "DEMO paper wallet — keys validated"
            return "FAILED", f"keys present but Binance rejected them: {probe.get('signed_detail')}"
        return "NOT REQUIRED", "DEMO paper wallet"
    if missing:
        return "FAILED", "Missing: " + ", ".join(missing)
    if probe.get("signed_ok"):
        return "OK", probe.get("signed_detail") or "signed account"
    return "FAILED", str(probe.get("signed_detail") or "unsigned")


def run_cockpit(*, once: bool = False) -> None:
    setup_logging()
    reload_env()
    settings = get_settings()

    if settings.trading_mode == "live" and not settings.live_unlocked:
        logger.error("LIVE confirmation missing — forcing DEMO. Set BINANCE_LIVE_CONFIRM=I_UNDERSTAND")
        os.environ["TRADING_MODE"] = "paper"
        settings = get_settings()

    pr = probe_binance(
        settings.binance_api_key,
        settings.binance_api_secret,
        testnet=settings.trading_mode == "testnet",
    )
    host = pr.get("public_host") if pr.get("signed_ok") or pr.get("public_ok") else None
    feed = MarketFeed(host=host, allow_demo=settings.allow_demo_tape)
    if host and (pr.get("signed_ok") or pr.get("public_ok")):
        feed._backend = "binance"
    market = CryptoMarketAdapter(feed=feed)
    broker = PaperBroker()
    brain = TradingAgentsBrain()
    ui = CockpitUI()
    state = load_state()
    stop = {"flag": False}
    keys = {"cmd": ""}
    started = time.time()
    reconnect_until = 0.0
    fail_streak = 0
    last_analyze = 0.0
    last_probe = time.time()

    auth_state, auth_detail = _auth_banner(settings, pr)
    nvidia = "set" if nvidia_key_present() else "MISSING — run python -m app setup"
    print(f"MODE: {settings.display_mode}")
    print(f"EXCHANGE AUTHENTICATION: {auth_state}")
    print(f"  {auth_detail}")
    print(f"NVIDIA: {nvidia}  Binance keys: {'OK' if pr.get('signed_ok') else pr.get('signed_detail') or 'none'}")
    print(f"market: {host or ('DEMO tape' if settings.allow_demo_tape else 'DISCONNECTED')}")
    print("BRAIN: TradingAgents")
    if settings.trading_mode == "live" and not settings.live_unlocked:
        print("LIVE locked — DEMO only.")

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
    logger.info("cockpit start brain=%s (%s) mode=%s", "ONLINE" if ok else "OFFLINE", detail, settings.display_mode)

    # Reconcile local paper book with exchange when live.
    state.synced = False
    try:
        acct0 = fetch_account(broker=broker, feed=feed, start_equity=state.start_equity)
        state.synced = bool(acct0.connected or settings.trading_mode == "paper")
        if acct0.auth == "FAILED" and settings.trading_mode != "paper":
            logger.error("EXCHANGE AUTHENTICATION: FAILED %s", acct0.auth_detail)
        save_state(state)
    except Exception:
        logger.exception("startup account fetch failed")
        state.synced = settings.trading_mode == "paper"

    view: dict = {"cycle": state.cycle, "watch": [], "health": {}, "account": {}, "stages": {}}

    while not stop["flag"]:
        cmd = keys.pop("cmd", "") or ""
        if cmd in {"q", "Q"}:
            break
        if cmd in {"p", "P"}:
            state.paused = True
            logger.info("EXECUTION: PAUSED (analysis stays on)")
        if cmd in {"r", "R"}:
            if state.emergency:
                logger.warning("emergency stop is latched — explicit resume required")
                if not HALT_FILE.exists():
                    state.emergency = False
                    state.paused = False
                    logger.info("emergency cleared by explicit resume")
            else:
                state.paused = False
                logger.info("EXECUTION: RESUMED")
        if cmd in {"e", "E"}:
            state.emergency = True
            state.paused = True
            n = cancel_entry_orders()
            logger.error("EMERGENCY STOP — cancelled %s entry orders; positions still monitored", n)
        if cmd in {"s", "S"}:
            state.page = "strategy"
        elif cmd in {"m", "M"}:
            state.page = "market"
        elif cmd in {"o", "O"}:
            state.page = "positions"
        elif cmd in {"t", "T"}:
            state.page = "trades"
        elif cmd in {"l", "L"}:
            state.page = "logs"
        elif cmd in {"h", "H"}:
            state.page = "help"
        elif cmd in {"q", "Q"}:
            break
        if HALT_FILE.exists():
            state.halted = True

        today = utc_day()
        if state.day != today:
            state.day = today
            state.start_equity = None
            if not state.goal_hit and not state.emergency:
                state.halted = False

        if time.time() < reconnect_until:
            view["health"] = {
                "Exchange": "DISCONNECTED",
                "Market": "DISCONNECTED",
                "Keys": auth_state,
                "TradingAgents": brain_status()["state"],
                "News": "OFFLINE",
                "Sentiment": "OFFLINE",
                "Execution": "BLOCKED",
            }
            view["paused"] = state.paused
            view["emergency"] = state.emergency
            view["uptime"] = _uptime(started)
            view["auth_line"] = f"{auth_state} — {auth_detail}"
            if once:
                print(ui.render(view))
                break
            ui.draw(view)
            time.sleep(1)
            continue

        try:
            ctx = market.context(list(settings.watchlist), settings.interval)
        except Exception as exc:
            fail_streak += 1
            backoff = min(60, 2 ** min(fail_streak, 5))
            reconnect_until = time.time() + backoff
            logger.error("market context failed (%s) — retry in %ss", exc, backoff)
            continue

        marks = {s.symbol: s.price for s in ctx.snapshots.values()}
        try:
            acct = fetch_account(broker=broker, feed=feed, marks=marks, start_equity=state.start_equity)
        except Exception as exc:
            fail_streak += 1
            backoff = min(60, 2 ** min(fail_streak, 5))
            reconnect_until = time.time() + backoff
            logger.error("account fetch failed (%s) — retry in %ss", exc, backoff)
            continue

        fail_streak = 0
        state.synced = bool(acct.connected or settings.allow_demo_tape)
        snap_acct = acct.to_dict()
        if state.start_equity is None:
            state.start_equity = float(snap_acct["equity"])
        start_eq = float(state.start_equity or snap_acct["equity"] or 1)
        day_pnl = float(snap_acct["equity"]) - start_eq
        day_pct = (day_pnl / start_eq * 100.0) if start_eq else 0.0
        snap_acct["day_pnl"] = day_pnl
        snap_acct["day_pnl_pct"] = day_pct
        snap_acct["total_pnl"] = snap_acct.get("total_pnl") or (float(snap_acct["equity"]) - settings.stake_usd)
        snap_acct["total_pnl_pct"] = snap_acct.get("total_pnl_pct") or (
            (float(snap_acct["equity"]) - settings.stake_usd) / settings.stake_usd * 100.0 if settings.stake_usd else 0
        )

        if goal_reached(float(snap_acct["equity"]), settings.goal_usd):
            state.halted = True
            state.goal_hit = True

        # Position monitor every tick.
        try:
            events = manage_positions(
                broker=broker,
                feed=feed,
                brackets=state.brackets,
                auto_execute=settings.auto_execute and not state.paused,
                halted_new=state.halted or state.emergency,
            )
            for ev in events:
                tid = trade_id(ev["symbol"])
                rec = {
                    "id": tid,
                    "symbol": ev["symbol"],
                    "side": "SELL",
                    "qty": ev.get("qty"),
                    "price": ev.get("price"),
                    "reason": ev.get("reason"),
                    "realized_pnl": ev.get("realized_pnl") or 0,
                }
                state.trades.append(rec)
                logger.info("%s position closed reason=%s", tid, ev.get("reason"))
            if events:
                acct = fetch_account(broker=broker, feed=feed, marks=marks, start_equity=state.start_equity)
                snap_acct = acct.to_dict()
                snap_acct["day_pnl_pct"] = day_pct
        except Exception:
            logger.exception("position monitor failed")

        status = brain_status()
        exchange_state = "ONLINE" if ctx.connected else ("DEMO" if settings.allow_demo_tape and ctx.snapshots else "DISCONNECTED")
        exec_state = "PAUSED" if (state.paused or state.emergency) else ("READY" if state.synced else "BLOCKED")
        view.update(
            {
                "clock": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
                "cycle": state.cycle,
                "account": snap_acct,
                "positions": snap_acct.get("positions") or [],
                "brackets": state.brackets,
                "trades": state.trades,
                "paused": state.paused,
                "emergency": state.emergency,
                "page": state.page,
                "uptime": _uptime(started),
                "auth_line": f"{acct.auth} — {acct.auth_detail}",
                "logs": tail_logs(16),
                "health": {
                    "Exchange": exchange_state,
                    "Binance": exchange_state,
                    "Market": exchange_state,
                    "Keys": "OK" if pr.get("signed_ok") else ("NONE" if not settings.binance_api_key else "FAIL"),
                    "TradingAgents": status["state"],
                    "News": ctx.news.status,
                    "Sentiment": ctx.sentiment.status if ctx.sentiment else "OFFLINE",
                    "Execution": exec_state,
                },
                "watch": [
                    {
                        "symbol": s.symbol,
                        "price": s.price,
                        "trend": s.trend,
                        "action": (view.get("last_actions") or {}).get(s.symbol, "—"),
                        "confidence": (view.get("last_conf") or {}).get(s.symbol, 0),
                    }
                    for s in ctx.snapshots.values()
                ],
            }
        )

        due = (time.time() - last_analyze) >= settings.loop_seconds or last_analyze == 0
        analyze_now = due and not state.halted and not state.emergency
        # Pause stops execution, not analysis.
        if analyze_now:
            state.cycle += 1
            last_analyze = time.time()
            cycle_rows: list[str] = []
            t_cycle = time.monotonic()
            logger.info("CYCLE #%s start", state.cycle)
            for symbol in settings.watchlist:
                if stop["flag"] or state.halted or state.emergency:
                    break
                cid = _cycle_id(symbol)
                logger.info("%s analysis started", cid)
                t0 = time.monotonic()

                def on_stage(name: str, status_s: str) -> None:
                    view.setdefault("stages", {})[name] = status_s

                snap = ctx.snapshots.get(to_binance(symbol))
                blob_parts = [ctx.note]
                if snap:
                    blob_parts.append(
                        f"{snap.symbol} last={snap.price} chg24h={snap.change_pct:+.2f}% "
                        f"RSI={snap.rsi:.1f} ATR%={snap.atr_pct:.2f} trend={snap.trend} "
                        f"EMA20={snap.ema20:.6g} EMA50={snap.ema50:.6g} ts={snap.timestamp} "
                        f"stale={snap.stale} structure={snap.structure}"
                    )
                if ctx.sentiment and ctx.sentiment.value is not None:
                    blob_parts.append(
                        f"FearGreed={ctx.sentiment.value} ({ctx.sentiment.classification})"
                    )
                else:
                    blob_parts.append("FearGreed=unavailable (not invented)")
                if ctx.news.headlines:
                    blob_parts.append(
                        "Headlines: " + " | ".join(h.get("title", "") for h in ctx.news.headlines[:4])
                    )
                else:
                    blob_parts.append("News wire unavailable (not invented)")

                try:
                    decision: TradeDecision = brain.analyze(
                        symbol,
                        cycle_id=cid,
                        market_note="\n".join(blob_parts),
                        on_stage=on_stage,
                    )
                except Exception as exc:
                    logger.exception("%s analysis crashed", cid)
                    decision = TradeDecision.failed(symbol, str(exc), cycle_id=cid)

                if decision.status != "ANALYSIS_FAILED" and decision.action != "HOLD":
                    attach_system_levels(decision, snap)
                    qty, notional, block = size_position(
                        equity=float(snap_acct["equity"]),
                        cash=float(snap_acct["cash"]),
                        price=float(snap.price if snap else 0),
                        stop=decision.stop_loss,
                        risk_per_trade=settings.risk_per_trade,
                        max_position_percent=settings.max_position_percent,
                        min_notional=settings.min_notional,
                    )
                    if block:
                        decision.reason = block
                        logger.info("%s ORDER BLOCKED Reason: %s", cid, block)
                    elif float(snap_acct["equity"]) > 0:
                        decision.position_size = min(0.90, notional / float(snap_acct["equity"]))

                view["decision"] = decision.to_dict()
                view["stages"] = decision.stages or view.get("stages") or {}
                view.setdefault("last_actions", {})[to_binance(symbol)] = (
                    decision.status if decision.status == "ANALYSIS_FAILED" else decision.action
                )
                view.setdefault("last_conf", {})[to_binance(symbol)] = decision.confidence
                state.decisions.append(
                    {
                        "cycle_id": cid,
                        "symbol": symbol,
                        "action": decision.action,
                        "status": decision.status,
                        "rating": decision.rating,
                        "thesis": (decision.thesis or "")[:400],
                        "ts": decision.timestamp,
                    }
                )
                save_state(state)

                latency = time.monotonic() - t0
                logger.info(
                    "%s decision=%s status=%s rating=%s brain_latency=%.2fs",
                    cid,
                    decision.action,
                    decision.status,
                    decision.rating,
                    latency,
                )
                cycle_rows.append(
                    f"{symbol}  TradingAgents  {latency:.1f}s  {decision.status or decision.action}  "
                    f"{int((decision.confidence or 0) * 100)}%"
                )

                if decision.status == "ANALYSIS_FAILED":
                    logger.error("%s ANALYSIS FAILED Reason: %s", cid, decision.error or decision.thesis)
                    continue

                gate = execution_gate(
                    decision,
                    snap=snap,
                    equity=float(snap_acct["equity"]),
                    cash=float(snap_acct["cash"]),
                    open_symbols=[p["symbol"] for p in snap_acct.get("positions") or []],
                    last_trade_iso=state.last_trade.get(to_binance(symbol)),
                    start_equity=float(state.start_equity or snap_acct["equity"]),
                    connected=ctx.connected or (settings.allow_demo_tape and bool(snap)),
                    paused=state.paused,
                    halted=state.halted,
                    emergency=state.emergency,
                    synced=state.synced,
                    exposure=sum(float(p.get("notional") or 0) for p in snap_acct.get("positions") or []),
                )
                if not gate.allow:
                    if gate.code == "HOLD":
                        logger.info("%s HOLD / SKIP %s", cid, gate.reason)
                    else:
                        logger.info("%s %s", cid, gate.blocked_line())
                        if view.get("decision"):
                            view["decision"]["status"] = "RISK_REJECTED"
                            view["decision"]["reason"] = gate.reason
                    continue
                if not settings.auto_execute:
                    logger.info("%s Execution: SKIPPED auto-execute off", cid)
                    continue
                tid = trade_id(to_binance(symbol))
                try:
                    logger.info("%s %s order submitted", cid, tid)
                    order = execute_decision(
                        symbol,
                        decision.rating,
                        float(decision.position_size),
                        float(snap.price if snap else 0),
                        reason=f"TradingAgents {decision.rating} {cid}",
                        broker=broker,
                    )
                except (ExecutionError, ValueError) as exc:
                    logger.error("%s EXECUTION FAILED %s Reason: %s", cid, tid, exc)
                    if view.get("decision"):
                        view["decision"]["status"] = "EXECUTION_FAILED"
                        view["decision"]["reason"] = str(exc)
                    continue
                if not order:
                    logger.info("%s Execution: SKIPPED empty fill", cid)
                    continue
                if str(order.get("status") or "").lower() not in {"filled", "partial"}:
                    logger.error("%s EXECUTION FAILED %s not confirmed: %s", cid, tid, order.get("status"))
                    continue
                logger.info("%s %s ORDER CONFIRMED %s %s", cid, tid, order.get("side"), order.get("qty"))
                if view.get("decision"):
                    view["decision"]["status"] = "EXECUTED"
                state.last_trade[to_binance(symbol)] = datetime.now(timezone.utc).isoformat()
                rec = {
                    "id": tid,
                    "symbol": to_binance(symbol),
                    "side": order.get("side"),
                    "qty": order.get("qty"),
                    "price": order.get("price"),
                    "reason": order.get("reason"),
                    "status": order.get("status"),
                    "decision": decision.rating,
                    "confidence": decision.confidence,
                    "venue": order.get("venue"),
                }
                state.trades.append(rec)
                if str(order.get("side") or "").upper() == "BUY" and snap:
                    ensure_bracket(
                        state.brackets,
                        to_binance(symbol),
                        float(order.get("price") or snap.price),
                        decision.stop_loss,
                        (decision.take_profit or [None])[0],
                        snap.atr,
                        settings.trail_atr,
                    )
                save_state(state)
                acct = fetch_account(broker=broker, feed=feed, marks=marks, start_equity=state.start_equity)
                snap_acct = acct.to_dict()
                snap_acct["day_pnl_pct"] = day_pct
            view["cycle"] = state.cycle
            view["account"] = snap_acct
            view["positions"] = snap_acct.get("positions") or []
            view["watch"] = [
                {
                    "symbol": s.symbol,
                    "price": s.price,
                    "trend": s.trend,
                    "action": (view.get("last_actions") or {}).get(s.symbol, "—"),
                    "confidence": (view.get("last_conf") or {}).get(s.symbol, 0),
                }
                for s in ctx.snapshots.values()
            ]
            view["cycle_line"] = (
                f"CYCLE #{state.cycle}  {time.monotonic() - t_cycle:.1f}s  "
                + " | ".join(cycle_rows)
            )
            state.cycle_log.append({"cycle": state.cycle, "line": view["cycle_line"]})
            logger.info("%s", view["cycle_line"])
            save_state(state)

        if time.time() - last_probe > 120:
            try:
                pr = probe_binance(
                    settings.binance_api_key,
                    settings.binance_api_secret,
                    testnet=settings.trading_mode == "testnet",
                )
                last_probe = time.time()
            except Exception:
                last_probe = time.time()

        if once:
            print(ui.render(view))
            break
        ui.draw(view)

        for _ in range(max(1, min(2, settings.manage_seconds))):
            if stop["flag"]:
                break
            time.sleep(1)

    ui.stop()
    save_state(state)
    logger.info("cockpit stopped")
