from app.binance.client import _FILTERS, quantize_qty


def test_quantize_floors_to_step():
    _FILTERS["FOOUSDT"] = (0.001, 0.001, 10.0)
    assert quantize_qty("FOOUSDT", 1.23456, price=20) == 1.234
    assert quantize_qty("FOOUSDT", 0.0004, price=20) == 0.0
    assert quantize_qty("FOOUSDT", 0.4, price=10) == 0.0  # 4 USDT < 10 notional
