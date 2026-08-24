from app.binance.indicators import compute_indicators, ema, rsi, sma
from app.models import Candle


def _candles(closes: list[float]) -> list[Candle]:
    out = []
    for i, close in enumerate(closes):
        high = close * 1.01
        low = close * 0.99
        out.append(
            Candle(
                open_time=i * 60_000,
                open=close,
                high=high,
                low=low,
                close=close,
                volume=100 + i,
                close_time=i * 60_000 + 59_999,
            )
        )
    return out


def test_sma_and_ema_on_flat_series():
    values = [10.0] * 20
    assert sma(values, 10) == 10.0
    assert ema(values, 10) == 10.0


def test_rsi_uptrend_is_high():
    closes = [float(i) for i in range(1, 40)]
    value = rsi(closes, 14)
    assert value > 70


def test_rsi_downtrend_is_low():
    closes = [float(i) for i in range(40, 0, -1)]
    value = rsi(closes, 14)
    assert value < 30


def test_full_indicator_set():
    closes = [100 + (i * 0.4) + ((-1) ** i) * 0.8 for i in range(80)]
    ind = compute_indicators(_candles(closes), change_24h=1.5)
    assert 0 < ind.rsi < 100
    assert ind.bb_upper > ind.bb_middle > ind.bb_lower
    assert ind.atr > 0
    assert ind.last_close == closes[-1]
