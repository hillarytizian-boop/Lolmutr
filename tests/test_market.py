
from binance_agent.market import ema, realized_volatility, rsi, sma


def test_indicators_handle_short_and_flat_series():
    assert sma([1, 2, 3], 20) == 2
    assert ema([5], 12) == 5
    assert rsi([10] * 20) == 50
    assert realized_volatility([10, 10, 10]) == 0


def test_rsi_distinguishes_rising_and_falling_markets():
    assert rsi(list(range(1, 30))) == 100
    assert rsi(list(range(30, 1, -1))) == 0


def test_realized_volatility_is_positive_for_moving_prices():
    assert realized_volatility([100, 102, 99, 104, 101]) > 0


def test_ema_weights_recent_prices():
    values = [10] * 10 + [20] * 5
    assert ema(values, 5) > sma(values, 14)
    assert ema(values, 5) < 20
