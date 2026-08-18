"""Headless auto-trader for Termux and any always-on host.

Analyzes the watchlist on a timer and, when gates pass, sends the PM ticket
to the paper book or (if unlocked) Binance. Stop with Ctrl+C or `touch data/HALT`.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.graph import TradingDesk
from app.binance.executor import ExecutionError, execute_decision
from app.binance.feed import MarketFeed
from app.binance.paper import PaperBroker
from app.config import DATA_DIR, HALT_FILE, get_settings
from app.store import RunStore

logger = logging.getLogger("lolmutr.auto")


@dataclass
class Gate:
    allow: bool
    reason: str


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"day": utc_day(), "start_equity": None, "last_trade": {}, "halted": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("day", utc_day())
    data.setdefault("start_equity", None)
    data.setdefault("last_trade", {})
    data.setdefault("halted", False)
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def should_trade(
    *,
    action: str,
    confidence: float,
    symbol: str,
    open_symbols: list[str],
    equity: float,
    start_equity: float,
    last_trade_iso: str | None,
    now: datetime,
    min_confidence: float,
    max_positions: int,
    max_daily_loss_pct: float,
    cooldown_minutes: int,
    halted: bool,
    live_locked: bool,
) -> Gate:
    if halted:
        return Gate(False, "halted")
    if live_locked:
        return Gate(False, "live trading locked")
    if action == "Hold":
        return Gate(False, "hold")
    if confidence < min_confidence:
        return Gate(False, f"confidence {confidence:.2f} < {min_confidence:.2f}")
    if start_equity and start_equity > 0:
        dd = (equity - start_equity) / start_equity * 100.0
        if dd <= -abs(max_daily_loss_pct):
            return Gate(False, f"daily loss {dd:.2f}% hit circuit breaker")
    if action == "Buy":
        if symbol in open_symbols:
            return Gate(False, "already long")
        if len(open_symbols) >= max_positions:
            return Gate(False, f"max positions {max_positions}")
    if action == "Sell" and symbol not in open_symbols:
        return Gate(False, "no position to sell")
    if last_trade_iso and cooldown_minutes > 0:
        try:
            last = datetime.fromisoformat(last_trade_iso)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (now - last).total_seconds() / 60.0
            if age < cooldown_minutes:
                return Gate(False, f"cooldown {age:.0f}/{cooldown_minutes}m")
        except ValueError:
            pass
    return Gate(True, "ok")


def _configure_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
        fh = logging.FileHandler(DATA_DIR / "autotrader.log", encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def _wake_lock() -> None:
    import shutil
    import subprocess

    lock = shutil.which("termux-wake-lock")
    if lock:
        subprocess.run([lock], check=False)


def run_autotrader(*, once: bool = False) -> None:
    _configure_logging()
    _wake_lock()
    settings = get_settings()
    if settings.trading_mode == "live" and not settings.live_unlocked:
        logger.error(
            "TRADING_MODE=live but BINANCE_LIVE_CONFIRM is not I_UNDERSTAND "
            "(or keys are missing). Refusing to start."
        )
        sys.exit(2)

    public = MarketFeed()
    broker = PaperBroker()
    desk = TradingDesk(public=public, broker=broker)
    store = RunStore()
    state_path = DATA_DIR / "autotrader.json"
    state = load_state(state_path)
    stop = {"flag": False}

    def _stop(*_args: object) -> None:
        stop["flag"] = True
        logger.info("stop requested — finishing this cycle")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info(
        "autotrader start mode=%s execute=%s llm=%s watchlist=%s interval=%s loop=%ss",
        settings.trading_mode,
        settings.auto_execute,
        settings.llm_provider or "none",
        ",".join(settings.watchlist),
        settings.interval,
        settings.loop_seconds,
    )
    logger.info("stop: Ctrl+C or  touch %s", HALT_FILE)

    cycle = 0
    while not stop["flag"]:
        if HALT_FILE.exists():
            logger.warning("HALT file present at %s — exiting", HALT_FILE)
            break
        cycle += 1
        try:
            _cycle(desk, broker, public, store, state, state_path, cycle)
        except Exception:
            logger.exception("cycle %s failed", cycle)
        if once or stop["flag"]:
            break
        for _ in range(max(1, settings.loop_seconds)):
            if stop["flag"] or HALT_FILE.exists():
                break
            time.sleep(1)

    save_state(state_path, state)
    logger.info("autotrader stopped after %s cycle(s)", cycle)


def _cycle(
    desk: TradingDesk,
    broker: PaperBroker,
    public: MarketFeed,
    store: RunStore,
    state: dict[str, Any],
    state_path: Path,
    cycle: int,
) -> None:
    settings = get_settings()
    today = utc_day()
    if state.get("day") != today:
        state["day"] = today
        state["start_equity"] = None
        state["halted"] = False

    marks: dict[str, float] = {}
    snap = broker.snapshot()
    for pos in snap["positions"]:
        try:
            marks[pos["symbol"]] = public.price(pos["symbol"])
        except Exception:
            continue
    snap = broker.snapshot(marks)
    if state.get("start_equity") is None:
        state["start_equity"] = float(snap["equity"])
        save_state(state_path, state)

    start_equity = float(state["start_equity"] or snap["equity"])
    dd = (float(snap["equity"]) - start_equity) / start_equity * 100.0 if start_equity else 0.0
    if dd <= -abs(settings.max_daily_loss_pct):
        state["halted"] = True
        save_state(state_path, state)
        logger.error("circuit breaker: daily %+.2f%% — no more tickets today", dd)

    logger.info(
        "cycle %s equity=%.2f day_pnl=%+.2f%% feed=%s positions=%s",
        cycle,
        snap["equity"],
        dd,
        getattr(public, "source", "?"),
        len(snap["positions"]),
    )

    open_symbols = [p["symbol"] for p in snap["positions"]]
    now = datetime.now(timezone.utc)
    live_locked = settings.trading_mode == "live" and not settings.live_unlocked

    for symbol in settings.watchlist:
        if HALT_FILE.exists() or state.get("halted"):
            break
        try:
            run = desk.analyze(symbol, interval=settings.interval, execute=False)
        except Exception:
            logger.exception("analyze failed for %s", symbol)
            continue
        store.add(run)
        decision = run["decision"]
        action = decision["action"]
        gate = should_trade(
            action=action,
            confidence=float(decision.get("confidence") or 0),
            symbol=symbol,
            open_symbols=open_symbols,
            equity=float(snap["equity"]),
            start_equity=start_equity,
            last_trade_iso=(state.get("last_trade") or {}).get(symbol),
            now=now,
            min_confidence=settings.min_confidence,
            max_positions=settings.max_positions,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            cooldown_minutes=settings.cooldown_minutes,
            halted=bool(state.get("halted")),
            live_locked=live_locked,
        )
        line = (
            f"  {symbol:10} {decision['rating']:12} {action:4} "
            f"conf={float(decision.get('confidence') or 0):.2f} "
            f"size={float(decision.get('size_pct') or 0):.1%}"
        )
        if not gate.allow:
            logger.info("%s  skip (%s)", line, gate.reason)
            continue
        if not settings.auto_execute:
            logger.info("%s  dry-run", line)
            continue
        try:
            order = execute_decision(
                symbol,
                decision["rating"],
                float(decision["size_pct"]),
                float(run["price"]),
                reason=f"auto {decision['rating']} {decision.get('engine')}",
                broker=broker,
            )
        except (ExecutionError, ValueError) as exc:
            logger.error("%s  order failed: %s", line, exc)
            continue
        if not order:
            logger.info("%s  no fill", line)
            continue
        state.setdefault("last_trade", {})[symbol] = now.isoformat()
        if order.get("side") == "BUY" and symbol not in open_symbols:
            open_symbols.append(symbol)
        if order.get("side") == "SELL" and symbol in open_symbols:
            open_symbols.remove(symbol)
        save_state(state_path, state)
        logger.info(
            "%s  FILL %s %.6g @ %s on %s",
            line,
            order.get("side"),
            order.get("qty"),
            order.get("price"),
            order.get("venue"),
        )
        snap = broker.snapshot(marks)
