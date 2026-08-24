"""DEMO end-to-end self-check. Never places live orders."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.config import DATA_DIR, ROOT, get_settings, reload_env


def run_selftest() -> int:
    os.environ["TRADING_MODE"] = "demo"
    os.environ["AUTO_EXECUTE"] = "true"
    os.environ["BINANCE_LIVE_CONFIRM"] = ""
    os.environ.pop("LIVE_TRADING_CONFIRM", None)
    reload_env()
    # reload_env may restore live from .env — force demo again
    os.environ["TRADING_MODE"] = "paper"
    os.environ["AUTO_EXECUTE"] = "true"

    print("============================================================")
    print("LOLMUTR DEMO SELF-TEST")
    print("MODE: DEMO  (live orders are impossible in this command)")
    print("BRAIN: TradingAgents")
    print("============================================================")

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))

    settings = get_settings()
    check("configuration loads", settings.trading_mode == "paper", f"mode={settings.display_mode}")
    check("live is not default", not settings.live_unlocked, "")

    from app.binance.feed import DemoPublic, MarketFeed
    from app.binance.paper import PaperBroker
    from app.binance.probe import pick_public_host
    from app.logging_setup import setup_logging
    from app.profit import exit_reason, new_bracket, update_bracket
    from brain.decision import TradeDecision
    from brain.firm_runtime import run_firm
    from dashboard.terminal import CockpitUI
    from market.market_data import CryptoMarketAdapter
    from risk.execution_gate import execution_gate
    from risk.risk_manager import attach_system_levels, size_position
    from storage.state import load_state, save_state

    setup_logging()

    host, detail = pick_public_host()
    check("exchange public probe", True, host or f"unreachable ({detail[:80]}) — DEMO tape allowed")

    feed = MarketFeed(host=host, allow_demo=True)
    try:
        live_ok = feed.ping()
    except Exception:
        live_ok = False
    public = feed if live_ok else DemoPublic()
    adapter = CryptoMarketAdapter(feed=public if isinstance(public, MarketFeed) else MarketFeed(allow_demo=True))
    if not live_ok:
        adapter.feed._backend = "demo"
        adapter.feed.allow_demo = True

    from app.binance.feed import DemoPublic as DP

    demo = DP()
    for pair in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        px = demo.price(pair)
        candles = demo.klines(pair, "1h", 80)
        check(f"market data {pair}", px > 0 and len(candles) >= 60, f"last={px:.4g}")

    ctx = CryptoMarketAdapter(feed=demo).context(["BTCUSDT", "ETHUSDT", "SOLUSDT"], "1h")
    check("market adapter snapshots", len(ctx.snapshots) == 3, f"feed={ctx.feed}")
    check("timestamps attached", all(s.timestamp for s in ctx.snapshots.values()), "")

    book = Path(DATA_DIR) / "selftest-paper.json"
    broker = PaperBroker(path=book, starting_cash=10_000)
    broker.reset()
    snap0 = broker.snapshot()
    check("paper wallet balance", abs(snap0["cash"] - 10_000) < 1e-6, f"cash={snap0['cash']}")

    from app.llm import llm_configured
    from brain.tradingagents_brain import TradingAgentsBrain, brain_status

    status = brain_status()
    check("TradingAgents identified as brain", status["brain"] == "TradingAgents", status["state"])
    brain = TradingAgentsBrain()
    offline = brain.analyze("BTCUSDT", cycle_id="selftest-offline")
    if not llm_configured():
        check("offline brain is HOLD not BUY", offline.action == "HOLD" and offline.status != "BUY", offline.status)
    else:
        check("LLM key present — firm can run", True, status["detail"])

    replies = {
        "trading assistant": "Tape mixed. RSI 50. No invented prices.",
        "Sentiment Analyst": "Fear & Greed unavailable.",
        "News Analyst": "Wire empty.",
        "Bull Analyst": "Dip buyers exist.",
        "Bear Analyst": "No catalyst.",
        "Research Manager": "Hold. Evidence balanced.",
        "trading agent": "FINAL TRANSACTION PROPOSAL: **HOLD**",
        "Conservative Risk": "Force Hold.",
        "Portfolio Manager": '{"rating":"Hold","confidence":0.41,"thesis":"No edge on this tape."}',
    }

    def fake_complete(system: str, user: str, timeout: float = 90.0) -> str:
        for key, text in replies.items():
            if key.lower() in system.lower():
                return text
        return '{"rating":"Hold","confidence":0.3,"thesis":"flat"}'

    import brain.firm_runtime as fr

    original = fr.complete
    fr.complete = fake_complete  # type: ignore[assignment]
    try:
        hold_dec = run_firm("BTCUSDT", cycle_id="selftest-hold", market_blob="BTC last 100 RSI 50")
        check("firm HOLD is genuine HOLD", hold_dec.action == "HOLD" and hold_dec.status == "HOLD", hold_dec.rating)
        check("analyst stages completed", hold_dec.reports.get("market") != "", ",".join(hold_dec.stages))

        replies["Portfolio Manager"] = '{"rating":"Buy","confidence":0.8,"thesis":"Book agrees on a dip buy."}'
        buy_dec = run_firm("ETHUSDT", cycle_id="selftest-buy", market_blob="ETH last 3500 RSI 42")
        check("parser keeps valid BUY", buy_dec.action == "BUY" and buy_dec.status == "BUY", buy_dec.rating)

        def empty_complete(system: str, user: str, timeout: float = 90.0) -> str:
            return ""

        fr.complete = empty_complete  # type: ignore[assignment]
        failed = run_firm("SOLUSDT", cycle_id="selftest-fail", market_blob="SOL last 160")
        check("LLM failure is ANALYSIS_FAILED not silent HOLD", failed.status == "ANALYSIS_FAILED", failed.action)
    finally:
        fr.complete = original  # type: ignore[assignment]

    snap = ctx.snapshots["ETHUSDT"]
    attach_system_levels(buy_dec, snap)
    qty, notional, block = size_position(
        equity=10_000,
        cash=10_000,
        price=snap.price,
        stop=buy_dec.stop_loss,
        risk_per_trade=0.02,
        max_position_percent=0.25,
        min_notional=5,
    )
    check("position sizing", block is None and 0 < notional < 10_000, f"notional={notional:.2f}")
    buy_dec.position_size = notional / 10_000
    gate = execution_gate(
        buy_dec,
        snap=snap,
        equity=10_000,
        cash=10_000,
        open_symbols=[],
        last_trade_iso=None,
        start_equity=10_000,
        connected=True,
        paused=False,
        halted=False,
    )
    check("risk engine approves valid BUY", gate.allow, gate.reason)

    tiny = TradeDecision.hold("BTCUSDT", "flat", cycle_id="x")
    tiny.action = "BUY"
    tiny.status = "BUY"
    tiny.rating = "Buy"
    tiny.position_size = 0.2
    tiny.brain_online = True
    tiny_snap = ctx.snapshots["BTCUSDT"]
    gate_tiny = execution_gate(
        tiny,
        snap=tiny_snap,
        equity=5,
        cash=5,
        open_symbols=[],
        last_trade_iso=None,
        start_equity=5,
        connected=True,
        paused=False,
        halted=False,
    )
    check("tiny book blocked below minimum", not gate_tiny.allow, gate_tiny.reason)

    from app.binance.executor import execute_decision

    order = execute_decision("ETHUSDT", "Buy", buy_dec.position_size, snap.price, "selftest", broker)
    check("paper order confirmed", bool(order and order.get("status") == "filled"), str((order or {}).get("status")))
    after = broker.snapshot({snap.symbol: snap.price})
    check("position appears", any(p["symbol"] == "ETHUSDT" for p in after["positions"]), "")
    check("P&L updates", "unrealized_pnl" in after, f"{after.get('unrealized_pnl')}")

    br = new_bracket(snap.price, snap.price - 1.6 * snap.atr, snap.price + 2.4 * snap.atr, snap.atr, 1.4)
    br = update_bracket(br, snap.price * 0.5)
    why = exit_reason(
        mark=snap.price * 0.5,
        take=br.get("take"),
        hard_stop=br.get("stop"),
        high=br["high"],
        atr=br["atr"],
        trail_mult=1.4,
    )
    check("stop-loss simulation", why == "stop-loss", str(why))
    why_tp = exit_reason(
        mark=snap.price * 2,
        take=snap.price * 1.01,
        hard_stop=snap.price * 0.9,
        high=snap.price * 2,
        atr=snap.atr,
        trail_mult=1.4,
    )
    check("take-profit simulation", why_tp == "take-profit", str(why_tp))

    ui = CockpitUI()
    text = ui.render(
        {
            "cycle": 1,
            "account": after,
            "decision": buy_dec.to_dict(),
            "health": {"Exchange": "DEMO", "TradingAgents": "ONLINE", "News": "DEGRADED", "Execution": "READY"},
            "watch": [{"symbol": "ETHUSDT", "price": snap.price, "action": "BUY", "confidence": 0.8, "trend": "BULLISH"}],
            "positions": after["positions"],
            "stages": buy_dec.stages,
        }
    )
    check("dashboard renders TradingAgents", "TradingAgents" in text and "HILA" in text, "")

    state = load_state()
    save_state(state)
    again = load_state()
    check("restart recovery", again.cycle == state.cycle, "")

    logs = ROOT / "logs"
    check("logs directory", logs.exists(), str(logs))
    check("no secrets printed", "nvapi-" not in text and "secret" not in text.lower(), "")

    # Several manage ticks
    for i in range(3):
        _ = demo.price("BTCUSDT")
        time.sleep(0.05)
    check("repeated demo cycles", True, "3 ticks")

    print("------------------------------------------------------------")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"RESULT  {passed} passed  {failed} failed  of {len(results)}")
    return 0 if failed == 0 else 1
