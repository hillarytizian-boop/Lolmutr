import pytest

from app.binance.symbols import (
    from_yahoo,
    is_known_crypto,
    normalize_pair,
    split_pair,
    to_binance,
    to_yahoo,
)


def test_normalizes_common_aliases():
    assert to_binance("btc-usd") == "BTCUSDT"
    assert to_binance("BTC/USDT") == "BTCUSDT"
    assert to_binance("ethusdt") == "ETHUSDT"
    assert to_yahoo("BTCUSDT") == "BTC-USD"
    assert to_yahoo("ETH-USD") == "ETH-USD"
    assert from_yahoo("BTC-USD") == "BTCUSDT"


def test_split_longest_quote_wins():
    assert split_pair("BTCUSDT") == ("BTC", "USDT")
    assert split_pair("SOLUSDC") == ("SOL", "USDC")


def test_rejects_junk():
    with pytest.raises(ValueError):
        normalize_pair("")
    with pytest.raises(ValueError):
        normalize_pair("../etc/passwd")
    with pytest.raises(ValueError):
        normalize_pair("BTC USDT!!!")


def test_known_crypto():
    assert is_known_crypto("BTCUSDT")
    assert is_known_crypto("SOL-USD")
    assert not is_known_crypto("FOOBARBAZ")
