from app.binance.probe import _clean, signed_account


def test_clean_strips_quotes():
    assert _clean('  "abc"  ') == "abc"
    assert _clean("'xyz'") == "xyz"


def test_missing_keys_fail_without_network():
    ok, detail, data = signed_account("https://api.binance.com", "", "")
    assert ok is False
    assert "missing" in detail
    assert data == {}
