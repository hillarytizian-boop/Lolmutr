import pytest

from binance_agent.storage import Store


def test_paper_orders_settle_atomically(tmp_path):
    store = Store(tmp_path / "test.sqlite3", "USDT", 1000)
    buy = store.execute_paper_order(
        symbol="BTCUSDT",
        base_asset="BTC",
        side="BUY",
        quantity=1,
        price=100,
    )
    balances = store.balances()
    assert buy.fee == pytest.approx(0.1)
    assert balances["USDT"]["free"] == pytest.approx(899.9)
    assert balances["BTC"]["free"] == pytest.approx(1)

    store.execute_paper_order(
        symbol="BTCUSDT",
        base_asset="BTC",
        side="SELL",
        quantity=0.5,
        price=110,
    )
    balances = store.balances()
    assert balances["BTC"]["free"] == pytest.approx(0.5)
    assert balances["USDT"]["free"] == pytest.approx(954.845)
    store.close()


def test_paper_order_rejects_insufficient_balance_without_mutation(tmp_path):
    store = Store(tmp_path / "test.sqlite3", "USDT", 100)
    with pytest.raises(ValueError, match="Insufficient"):
        store.execute_paper_order(
            symbol="BTCUSDT",
            base_asset="BTC",
            side="BUY",
            quantity=2,
            price=100,
        )
    assert store.balances()["USDT"]["free"] == 100
    assert store.list_orders() == []
    store.close()


def test_runs_are_persisted(tmp_path):
    store = Store(tmp_path / "test.sqlite3", "USDT", 100)
    run = store.create_run("BTCUSDT", False)
    updated = store.update_run(
        run.id,
        status="completed",
        stage="Complete",
        result={"analysis": {"rating": "Hold"}},
    )
    assert updated.status == "completed"
    assert store.get_run(run.id).result["analysis"]["rating"] == "Hold"
    store.close()
