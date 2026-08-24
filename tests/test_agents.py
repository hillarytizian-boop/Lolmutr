from app.agents.analysts import market_analyst, news_analyst, sentiment_analyst
from app.agents.portfolio import portfolio_manager
from app.agents.researchers import bear_researcher, bull_researcher, research_manager
from app.agents.risk import risk_committee, risk_multiplier
from app.agents.trader import trader_agent
from app.models import Indicators


def _ind(**overrides) -> Indicators:
    base = dict(
        last_close=100.0,
        change_24h=1.0,
        rsi=50.0,
        macd=0.1,
        macd_signal=0.05,
        macd_hist=0.05,
        ema20=99.0,
        ema50=97.0,
        sma20=98.5,
        bb_upper=104.0,
        bb_middle=98.5,
        bb_lower=93.0,
        atr=2.0,
        atr_pct=2.0,
        volume=1200,
        volume_sma=1000,
        high_20=105.0,
        low_20=90.0,
        stoch_k=55.0,
    )
    base.update(overrides)
    return Indicators(**base)


def test_oversold_market_is_bullish():
    report = market_analyst("BTCUSDT", _ind(rsi=22, last_close=94, bb_lower=93, bb_upper=110))
    assert report.score > 0
    assert report.stance in {"Bullish", "Neutral"}


def test_overbought_market_is_bearish():
    report = market_analyst(
        "BTCUSDT",
        _ind(
            rsi=82,
            last_close=109,
            ema20=110,
            ema50=111,
            macd=-0.2,
            macd_signal=-0.05,
            macd_hist=-0.15,
            bb_upper=108,
            bb_lower=90,
        ),
    )
    assert report.score < 0


def test_extreme_fear_is_contrarian_bid():
    report = sentiment_analyst("ETHUSDT", {"value": 18, "classification": "Extreme Fear"}, [])
    assert report.score > 0


def test_news_keywords():
    headlines = [
        {"title": "Bitcoin ETF inflows hit record as rally continues"},
        {"title": "Hack and lawsuit rumours shake smaller tokens"},
    ]
    report = news_analyst("BTCUSDT", headlines)
    assert report.signals


def test_full_native_pipeline_emits_5_tier_rating():
    ind = _ind(rsi=28, last_close=95, ema20=96, ema50=94)
    analysts = [
        market_analyst("BTCUSDT", ind),
        sentiment_analyst("BTCUSDT", {"value": 30}, []),
        news_analyst("BTCUSDT", [{"title": "adoption surge for bitcoin"}]),
    ]
    bull = bull_researcher(analysts, "BTCUSDT", ind.last_close)
    bear = bear_researcher(analysts, "BTCUSDT", ind.last_close)
    plan = research_manager(analysts, bull, bear)
    trader = trader_agent(plan, ind)
    risk = risk_committee(trader, ind)
    decision = portfolio_manager(plan, trader, risk, ind, "binance-native", risk_multiplier(ind))
    assert decision.rating in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
    assert decision.action in {"Buy", "Hold", "Sell"}
    assert 0 <= decision.confidence <= 1
    if decision.action == "Buy":
        assert decision.stop_loss is not None
        assert decision.stop_loss < decision.entry
