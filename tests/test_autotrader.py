from datetime import datetime, timezone

from app.autotrader import Gate, should_trade
from app.cli import HELP, main
from app.llm import parse_llm_rating


def _gate(**overrides) -> Gate:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    base = dict(
        action="Buy",
        confidence=0.8,
        symbol="BTCUSDT",
        open_symbols=[],
        equity=10_000.0,
        start_equity=10_000.0,
        last_trade_iso=None,
        now=now,
        min_confidence=0.58,
        max_positions=3,
        max_daily_loss_pct=5.0,
        cooldown_minutes=45,
        halted=False,
        live_locked=False,
    )
    base.update(overrides)
    return should_trade(**base)


def test_hold_is_skipped():
    assert _gate(action="Hold").allow is False


def test_low_confidence_is_skipped():
    g = _gate(confidence=0.2)
    assert g.allow is False
    assert "confidence" in g.reason


def test_no_pyramid():
    assert _gate(open_symbols=["BTCUSDT"]).allow is False


def test_max_positions():
    assert _gate(open_symbols=["ETHUSDT", "SOLUSDT", "BNBUSDT"], max_positions=3).allow is False


def test_sell_without_position():
    assert _gate(action="Sell").allow is False


def test_sell_with_position_ok():
    assert _gate(action="Sell", open_symbols=["BTCUSDT"]).allow is True


def test_daily_loss_breaker():
    g = _gate(equity=9400, start_equity=10_000, max_daily_loss_pct=5)
    assert g.allow is False
    assert "circuit" in g.reason


def test_cooldown_blocks_new_buys_only():
    g = _gate(last_trade_iso="2026-08-18T11:30:00+00:00", cooldown_minutes=45)
    assert g.allow is False
    sell = _gate(
        action="Sell",
        open_symbols=["BTCUSDT"],
        last_trade_iso="2026-08-18T11:30:00+00:00",
        cooldown_minutes=45,
    )
    assert sell.allow is True


def test_live_locked():
    assert _gate(live_locked=True).allow is False


def test_happy_buy():
    assert _gate().allow is True


def test_parse_llm_json():
    parsed = parse_llm_rating('{"rating":"overweight","confidence":0.7,"thesis":"tape is bid"}')
    assert parsed is not None
    assert parsed["rating"] == "Overweight"
    assert parsed["confidence"] == 0.7


def test_parse_llm_prose():
    parsed = parse_llm_rating("**Rating**: Hold\nNo edge.")
    assert parsed is not None
    assert parsed["rating"] == "Hold"


def test_cli_help(capsys):
    main(["help"])
    out = capsys.readouterr().out
    assert "trade" in out
    assert "setup" in HELP
