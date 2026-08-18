from app.binance.feed import DemoPublic
from app.binance.indicators import compute_indicators


def test_demo_klines_are_long_enough_for_indicators():
    feed = DemoPublic()
    candles = feed.klines("BTCUSDT", "1h", 200)
    assert len(candles) >= 60
    ind = compute_indicators(candles, change_24h=1.0)
    assert ind.last_close > 0
    assert 0 < ind.rsi < 100


def test_demo_ticker_and_book():
    feed = DemoPublic()
    tick = feed.ticker("eth-usd")
    assert tick["symbol"] == "ETHUSDT"
    assert tick["price"] > 0
    book = feed.depth("ETHUSDT")
    assert book["bids"][0][0] < book["asks"][0][0]


def test_demo_path_is_deterministic_within_a_bar():
    feed = DemoPublic()
    a = [c.close for c in feed.klines("SOLUSDT", "1h", 80)]
    b = [c.close for c in feed.klines("SOLUSDT", "1h", 80)]
    assert a == b


def test_ticker_matches_last_hourly_close():
    feed = DemoPublic()
    last = feed.klines("BTCUSDT", "1h", 200)[-1].close
    assert feed.ticker("BTCUSDT")["price"] == last
    assert feed.price("BTCUSDT") == last
