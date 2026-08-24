def test_trade_path_imports():
    from app.cli import main
    from app.cockpit import run_cockpit
    from brain.tradingagents_brain import TradingAgentsBrain

    assert callable(main)
    assert callable(run_cockpit)
    assert TradingAgentsBrain.name == "TradingAgents"
