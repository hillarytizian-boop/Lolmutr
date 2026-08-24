from pathlib import Path

import pytest

from app.binance.paper import PaperBroker


def test_buy_and_sell_round_trip(tmp_path: Path):
    broker = PaperBroker(path=tmp_path / "paper.json", starting_cash=10_000)
    buy = broker.market_order("BTCUSDT", "BUY", notional=1000, price=100)
    assert buy["status"] == "filled"
    snap = broker.snapshot({"BTCUSDT": 110})
    assert snap["positions"][0]["qty"] == pytest.approx(10.0, rel=1e-6)
    assert snap["unrealized_pnl"] == pytest.approx(100.0, rel=1e-2)
    sell = broker.market_order("BTCUSDT", "SELL", quantity=10, price=110)
    assert sell["realized_pnl"] > 0
    done = broker.snapshot()
    assert done["positions"] == []
    assert done["cash"] > 10_000


def test_rejects_insufficient_cash(tmp_path: Path):
    broker = PaperBroker(path=tmp_path / "paper.json", starting_cash=50)
    with pytest.raises(ValueError):
        broker.market_order("ETHUSDT", "BUY", notional=200, price=10)


def test_reset(tmp_path: Path):
    broker = PaperBroker(path=tmp_path / "paper.json", starting_cash=500)
    broker.market_order("SOLUSDT", "BUY", notional=100, price=20)
    broker.reset()
    assert broker.snapshot()["cash"] == 500
    assert broker.snapshot()["positions"] == []
