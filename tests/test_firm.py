from brain.firm_runtime import run_firm


def test_firm_uses_pm_json_not_oneshot(monkeypatch):
    replies = {
        "Market Analyst": "RSI mid, trend mixed.",
        "Sentiment Analyst": "No Fear and Greed feed.",
        "News Analyst": "Wire empty.",
        "Bull Researcher": "Dip buyers exist.",
        "Bear Researcher": "No catalyst.",
        "Trader": "Hold.",
        "Risk committee": "Stay flat.",
        "Portfolio Manager": '{"rating":"Hold","confidence":0.4,"thesis":"No edge."}',
    }

    def fake_complete(system, user, timeout=90.0):
        for key, text in replies.items():
            if key.split()[0] in system or key in system:
                return text
        return '{"rating":"Hold","confidence":0.3,"thesis":"flat"}'

    monkeypatch.setattr("brain.firm_runtime.complete", fake_complete)
    decision = run_firm("BTCUSDT", cycle_id="t1", market_blob="BTC last 100 RSI 50")
    assert decision.brain == "TradingAgents"
    assert decision.action == "HOLD"
    assert decision.brain_online is True
    assert decision.reports.get("market")
