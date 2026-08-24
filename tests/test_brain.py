from datetime import datetime, timezone
from pathlib import Path

from app.binance.feed import DemoPublic
from app.binance.paper import PaperBroker
from brain.decision import TradeDecision
from brain.tradingagents_brain import TradingAgentsBrain
from market.market_data import SymbolSnapshot
from risk.execution_gate import execution_gate


def test_nvidia_glm_is_default_provider():
    from app.llm import PROVIDERS

    assert "nvidia" in PROVIDERS
    assert PROVIDERS["nvidia"]["env"] == "NVIDIA_API_KEY"
    assert PROVIDERS["nvidia"]["model"] == "z-ai/glm-5.2"


def test_nvidia_key_marks_brain_online(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    from brain.tradingagents_brain import brain_status

    status = brain_status()
    assert status["state"] == "ONLINE"
    assert status["llm_key_present"] is True


def test_offline_brain_is_hold_never_buy():
    brain = TradingAgentsBrain()
    decision = brain.analyze("BTCUSDT", cycle_id="test-offline")
    assert decision.brain == "TradingAgents"
    assert decision.action == "HOLD"
    assert decision.position_size == 0
    assert decision.brain_online is False
    assert "offline" in decision.thesis.lower() or "not installed" in decision.thesis.lower() or "no llm" in decision.thesis.lower() or "failed" in decision.thesis.lower() or "key" in decision.thesis.lower()


def test_gate_never_promotes_hold():
    decision = TradeDecision.hold("ETHUSDT", "flat", cycle_id="c1")
    snap = SymbolSnapshot(
        symbol="ETHUSDT",
        price=3000,
        change_pct=1,
        volume=1,
        atr=20,
        atr_pct=0.6,
        rsi=50,
        ema20=2990,
        ema50=2980,
        trend="NEUTRAL",
        stale=False,
        fetched_at=datetime.now(timezone.utc).timestamp(),
    )
    gate = execution_gate(
        decision,
        snap=snap,
        equity=10,
        cash=10,
        open_symbols=[],
        last_trade_iso=None,
        start_equity=10,
        connected=True,
        paused=False,
        halted=False,
    )
    assert gate.allow is False
    assert gate.code == "HOLD"


def test_gate_too_small(monkeypatch):
    monkeypatch.setenv("MIN_NOTIONAL", "10")
    monkeypatch.setenv("STAKE_USD", "5")
    decision = TradeDecision(
        symbol="BTCUSDT",
        action="BUY",
        confidence=0.8,
        entry=100,
        stop_loss=95,
        take_profit=[110],
        position_size=0.5,
        risk_reward=2,
        thesis="ta",
        bull_case="",
        bear_case="",
        risk_assessment="",
        portfolio_decision="Buy",
        timestamp="",
        brain="TradingAgents",
        cycle_id="c2",
        rating="Buy",
        brain_online=True,
    )
    snap = SymbolSnapshot(
        symbol="BTCUSDT",
        price=100,
        change_pct=0,
        volume=1,
        atr=2,
        atr_pct=2,
        rsi=50,
        ema20=99,
        ema50=98,
        trend="BULLISH",
        stale=False,
        fetched_at=datetime.now(timezone.utc).timestamp(),
    )
    gate = execution_gate(
        decision,
        snap=snap,
        equity=5,
        cash=5,
        open_symbols=[],
        last_trade_iso=None,
        start_equity=5,
        connected=True,
        paused=False,
        halted=False,
    )
    assert gate.allow is False
    assert "TOO SMALL" in gate.reason or gate.code == "TOO_SMALL"


def test_desk_stays_flat_without_tradingagents(tmp_path: Path):
    from app.agents.graph import TradingDesk

    desk = TradingDesk(
        public=DemoPublic(),
        broker=PaperBroker(path=tmp_path / "p.json", starting_cash=10),
    )
    run = desk.analyze(
        "BTCUSDT",
        extra_context={"headlines": [], "fear_greed": None},
        execute=True,
    )
    assert run["decision"]["engine"] == "TradingAgents"
    assert run["decision"]["action"] == "Hold"
    assert run["order"] is None
