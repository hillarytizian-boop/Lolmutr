from pathlib import Path

from app.agents.graph import TradingDesk
from app.binance.feed import DemoPublic
from app.binance.paper import PaperBroker


def test_desk_runs_end_to_end_on_demo_feed(tmp_path: Path):
    desk = TradingDesk(
        public=DemoPublic(),
        broker=PaperBroker(path=tmp_path / "paper.json", starting_cash=10_000),
    )
    run = desk.analyze(
        "BTCUSDT",
        interval="1h",
        execute=False,
        extra_context={"headlines": [], "fear_greed": {"value": 40}},
    )
    assert run["symbol"] == "BTCUSDT"
    assert run["yahoo_symbol"] == "BTC-USD"
    assert run["decision"]["rating"] in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
    assert len(run["reports"]) >= 8
    names = {r["name"] for r in run["reports"]}
    assert "Market Analyst" in names
    assert "Trader" in names
    assert "Research Manager" in names
    assert run["decision"]["engine"] in {"binance-native", "trading-agent", "TradingAgents"}
    assert run["decision"]["action"] in {"Buy", "Hold", "Sell"}
