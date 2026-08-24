import os
from datetime import datetime, timezone

from app.config import get_settings
from app.llm import llm_configured, llm_key_present
from brain.decision import TradeDecision
from brain.tradingagents_brain import TradingAgentsBrain
from market.market_data import SymbolSnapshot
from risk.execution_gate import execution_gate
from risk.risk_manager import size_position


def _snap(**kw) -> SymbolSnapshot:
    base = dict(
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
    base.update(kw)
    return SymbolSnapshot(**base)


def test_demo_alias_is_paper_display_demo(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "demo")
    monkeypatch.delenv("BINANCE_LIVE_CONFIRM", raising=False)
    s = get_settings()
    assert s.trading_mode == "paper"
    assert s.display_mode == "DEMO"
    assert s.live_unlocked is False


def test_live_without_confirm_is_locked(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("BINANCE_API_KEY", "x")
    monkeypatch.setenv("BINANCE_API_SECRET", "y")
    monkeypatch.setenv("BINANCE_LIVE_CONFIRM", "")
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    s = get_settings()
    assert s.live_unlocked is False
    assert s.signed_ready is False


def test_live_confirm_true_unlocks(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("BINANCE_API_KEY", "x")
    monkeypatch.setenv("BINANCE_API_SECRET", "y")
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "true")
    monkeypatch.setenv("BINANCE_LIVE_CONFIRM", "true")
    s = get_settings()
    assert s.live_unlocked is True


def test_nvidia_alias(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-test-alias")
    from app.config import alias_secrets

    alias_secrets()
    assert os.environ.get("NVIDIA_API_KEY") == "nvapi-test-alias"
    assert llm_key_present() is True


def test_llm_configured_false_without_key(monkeypatch):
    for name in (
        "NVIDIA_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVAPI_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    assert llm_configured() is False


def test_analysis_failed_is_not_hold(monkeypatch):
    dec = TradeDecision.failed("SOLUSDT", "LLM timed out", cycle_id="c-fail")
    assert dec.status == "ANALYSIS_FAILED"
    assert dec.action == "HOLD"
    gate = execution_gate(
        dec,
        snap=_snap(),
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
    assert gate.code == "ANALYSIS_FAILED"


def test_missing_confidence_does_not_kill_buy():
    dec = TradeDecision(
        symbol="BTCUSDT",
        action="BUY",
        confidence=0.0,
        entry=100,
        stop_loss=95,
        take_profit=[110],
        position_size=0.2,
        risk_reward=2,
        thesis="PM said Buy",
        bull_case="",
        bear_case="",
        risk_assessment="",
        portfolio_decision="Buy",
        timestamp="",
        brain="TradingAgents",
        cycle_id="c3",
        rating="Buy",
        brain_online=True,
        status="BUY",
        confidence_provided=False,
    )
    gate = execution_gate(
        dec,
        snap=_snap(),
        equity=1000,
        cash=1000,
        open_symbols=[],
        last_trade_iso=None,
        start_equity=1000,
        connected=True,
        paused=False,
        halted=False,
    )
    assert gate.allow is True


def test_size_never_uses_full_account():
    qty, notional, err = size_position(
        equity=10,
        cash=10,
        price=100,
        stop=98,
        risk_per_trade=1.0,
        max_position_percent=1.0,
        min_notional=5,
    )
    assert err is None
    assert notional <= 9.0 + 1e-9
    assert qty * 100 < 10


def test_size_blocks_five_dollar_book():
    qty, notional, err = size_position(
        equity=5,
        cash=5,
        price=100,
        stop=90,
        risk_per_trade=0.02,
        max_position_percent=0.25,
        min_notional=10,
    )
    assert qty == 0
    assert err is not None
    assert "MINIMUM" in err


def test_offline_status_hold_not_failed():
    brain = TradingAgentsBrain()
    decision = brain.analyze("BTCUSDT", cycle_id="off")
    assert decision.action == "HOLD"
    assert decision.status in {"HOLD", "ANALYSIS_FAILED"}
    if not decision.brain_online:
        assert decision.action != "BUY"
