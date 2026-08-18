from fastapi.testclient import TestClient

from binance_agent.app import app


def test_status_and_dashboard_start_in_paper_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_MODE", "paper")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CONTROL_API_TOKEN", raising=False)
    with TestClient(app) as client:
        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["mode"] == "paper"
        assert status.json()["control_auth_required"] is False
        assert client.get("/api/health").json()["status"] == "ok"
        assert "Northstar" in client.get("/").text


def test_control_token_protects_mutating_routes(monkeypatch, tmp_path):
    token = "correct-horse-battery-staple"
    monkeypatch.setenv("APP_MODE", "paper")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONTROL_API_TOKEN", token)
    with TestClient(app) as client:
        payload = {"symbol": "BTCUSDT", "execute": False}
        assert client.post("/api/runs", json=payload).status_code == 401
        accepted = client.post(
            "/api/runs", json=payload, headers={"X-Control-Token": token}
        )
        assert accepted.status_code == 202
