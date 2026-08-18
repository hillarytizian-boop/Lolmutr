from datetime import UTC, datetime

import pytest

from binance_agent.config import Settings
from binance_agent.models import AnalysisResult, MarketSnapshot
from binance_agent.risk import RiskEngine


def market(price=100):
    return MarketSnapshot(
        symbol="BTCUSDT",
        price=price,
        change_24h_pct=2,
        high_24h=105,
        low_24h=95,
        volume_24h=1000,
        quote_volume_24h=100_000,
        rsi_14=58,
        sma_20=99,
        sma_50=97,
        ema_12=99,
        ema_26=98,
        volatility_pct=2,
        updated_at=datetime.now(UTC),
    )


def settings(**kwargs):
    defaults = {
        "symbols": ("BTCUSDT",),
        "risk_per_trade_pct": 1,
        "max_position_pct": 15,
        "min_confidence": 62,
        "stop_loss_pct": 2,
        "take_profit_pct": 4,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def analysis(rating="Buy", confidence=80):
    return AnalysisResult(
        rating=rating,
        confidence=confidence,
        summary="test",
        source="demo",
    )


def test_buy_is_risk_sized_then_capped_by_position_limit():
    engine = RiskEngine(settings())
    plan = engine.build_plan(
        symbol="BTCUSDT",
        analysis=analysis(),
        market=market(),
        balances={"USDT": {"free": 10_000, "locked": 0}},
    )
    assert plan.action == "BUY"
    assert plan.executable
    assert plan.notional == pytest.approx(1500)
    assert plan.quantity == pytest.approx(15)
    assert plan.risk_amount == pytest.approx(30)
    assert plan.stop_loss == pytest.approx(98)
    assert plan.take_profit == pytest.approx(104)


def test_confidence_gate_forces_hold():
    plan = RiskEngine(settings()).build_plan(
        symbol="BTCUSDT",
        analysis=analysis(confidence=61),
        market=market(),
        balances={"USDT": {"free": 10_000}},
    )
    assert plan.action == "HOLD"
    assert not plan.executable
    assert "below" in plan.reason


def test_spot_sell_cannot_open_a_short():
    plan = RiskEngine(settings()).build_plan(
        symbol="BTCUSDT",
        analysis=analysis(rating="Sell"),
        market=market(),
        balances={"USDT": {"free": 10_000}},
    )
    assert plan.action == "HOLD"
    assert "no base asset" in plan.reason.lower()


def test_underweight_reduces_half_of_position():
    plan = RiskEngine(settings()).build_plan(
        symbol="BTCUSDT",
        analysis=analysis(rating="Underweight"),
        market=market(),
        balances={"USDT": {"free": 500}, "BTC": {"free": 2}},
    )
    assert plan.action == "SELL"
    assert plan.quantity == 1
