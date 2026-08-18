import pytest

from binance_agent.config import Settings


def test_default_environment_is_safe_paper_mode(monkeypatch, tmp_path):
    for name in (
        "APP_MODE",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "BINANCE_LIVE_TRADING",
        "AUTO_EXECUTE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.mode == "paper"
    assert not settings.live_trading_enabled
    assert not settings.auto_execute


def test_live_mode_requires_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_MODE", "live")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(ValueError, match="required in live mode"):
        Settings.from_env()


def test_live_mode_requires_long_control_token(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_MODE", "live")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    monkeypatch.setenv("CONTROL_API_TOKEN", "too-short")
    with pytest.raises(ValueError, match="CONTROL_API_TOKEN"):
        Settings.from_env()


def test_symbols_must_match_quote_asset(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_MODE", "paper")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_SYMBOLS", "BTCUSDT,ETHBTC")
    monkeypatch.setenv("BINANCE_QUOTE_ASSET", "USDT")
    with pytest.raises(ValueError, match="must end in USDT"):
        Settings.from_env()
