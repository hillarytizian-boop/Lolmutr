"""Trading desk graph — TradingAgents firm, Binance-native data path.

Pipeline (mirrors Tauric Research):
    analysts (market, sentiment, news, structure)
        → bull / bear debate
        → research manager
        → trader
        → risk committee
        → portfolio manager
        → optional paper / testnet order
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.agents.analysts import (
    market_analyst,
    news_analyst,
    sentiment_analyst,
    structure_analyst,
)
from app.agents.context import fetch_fear_greed, fetch_news
from app.agents.llm_bridge import probe, run_tradingagents
from app.agents.portfolio import portfolio_manager
from app.llm import overlay_decision
from app.profit import profit_size_pct
from app.agents.researchers import bear_researcher, bull_researcher, research_manager
from app.agents.risk import risk_committee, risk_multiplier
from app.agents.trader import trader_agent
from app.binance.client import BinancePublic
from app.binance.executor import execute_decision
from app.binance.feed import MarketFeed
from app.binance.indicators import compute_indicators
from app.binance.paper import PaperBroker
from app.binance.symbols import to_binance, to_yahoo
from app.models import AnalysisRun, Decision


class TradingDesk:
    def __init__(
        self,
        public: BinancePublic | MarketFeed | None = None,
        broker: PaperBroker | None = None,
    ) -> None:
        self.public = public or MarketFeed()
        self.broker = broker or PaperBroker()

    def analyze(
        self,
        symbol: str,
        interval: str = "1h",
        execute: bool = False,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pair = to_binance(symbol)
        ticker = self.public.ticker(pair)
        candles = self.public.klines(pair, interval=interval, limit=200)
        depth = self.public.depth(pair, limit=20)
        ind = compute_indicators(candles, change_24h=ticker["change_pct"])

        ctx = extra_context or {}
        headlines = ctx.get("headlines")
        fear_greed = ctx.get("fear_greed")
        if headlines is None:
            headlines = fetch_news()
        if fear_greed is None:
            fear_greed = fetch_fear_greed()

        analysts = [
            market_analyst(pair, ind),
            sentiment_analyst(pair, fear_greed, headlines),
            news_analyst(pair, headlines),
            structure_analyst(pair, ind, depth),
        ]
        bull = bull_researcher(analysts, pair, ind.last_close)
        bear = bear_researcher(analysts, pair, ind.last_close)
        plan = research_manager(analysts, bull, bear)
        trader = trader_agent(plan, ind)
        risk = risk_committee(trader, ind)
        vol_mult = risk_multiplier(ind)

        engine = "binance-native"
        ta_result = run_tradingagents(pair)
        if ta_result and ta_result.get("rating"):
            engine = "tradingagents+binance"
            # Official graph wins the rating; we keep Binance levels / sizing.
            plan.stance = str(ta_result["rating"])
            plan.details = (
                f"{plan.details}\n\nTradingAgents overlay ({to_yahoo(pair)}): "
                f"{ta_result.get('final_trade_decision') or ta_result['rating']}"
            )

        decision: Decision = portfolio_manager(
            plan, trader, risk, ind, engine=engine, vol_mult=vol_mult
        )
        if ta_result and ta_result.get("rating"):
            decision.rating = str(ta_result["rating"])
            decision.action = {
                "Buy": "Buy",
                "Overweight": "Buy",
                "Hold": "Hold",
                "Underweight": "Sell",
                "Sell": "Sell",
            }.get(decision.rating, decision.action)
        elif engine == "binance-native":
            decision = overlay_decision(
                decision, [*analysts, bull, bear, plan, trader, *risk],
                pair, ind.last_close, vol_mult,
            )

        order = None
        if execute:
            order = execute_decision(
                pair,
                decision.rating,
                decision.size_pct,
                ind.last_close,
                reason=f"{decision.rating} via {decision.engine}",
                broker=self.broker,
            )

        reports = [r.to_dict() for r in (*analysts, bull, bear, plan, trader, *risk)]
        run = AnalysisRun(
            id=uuid.uuid4().hex[:12],
            symbol=pair,
            interval=interval,
            created_at=datetime.now(timezone.utc).isoformat(),
            price=ind.last_close,
            indicators=ind.to_dict(),
            reports=reports,
            debate=[bull.to_dict(), bear.to_dict()],
            decision=decision.to_dict(),
            order=order,
        )
        payload = run.to_dict()
        payload["ticker"] = ticker
        payload["depth"] = depth
        payload["yahoo_symbol"] = to_yahoo(pair)
        payload["probe"] = probe()
        payload["fear_greed"] = fear_greed
        payload["headlines"] = headlines[:8]
        payload["tradingagents"] = ta_result
        return payload
