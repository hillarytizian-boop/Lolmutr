from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .models import AnalysisResult, MarketSnapshot, Rating

_ALLOWED_RATINGS = {"Buy", "Overweight", "Hold", "Underweight", "Sell"}


def yahoo_crypto_symbol(binance_symbol: str, quote_asset: str) -> str:
    base = binance_symbol.removesuffix(quote_asset)
    return f"{base}-USD"


def _technical_score(market: MarketSnapshot) -> tuple[int, list[str], list[str]]:
    bullish: list[str] = []
    bearish: list[str] = []
    if market.price > market.sma_20:
        bullish.append("price is above the 20-hour average")
    else:
        bearish.append("price is below the 20-hour average")
    if market.sma_20 > market.sma_50:
        bullish.append("the 20/50-hour trend is positive")
    else:
        bearish.append("the 20/50-hour trend is negative")
    if market.ema_12 > market.ema_26:
        bullish.append("short momentum is expanding")
    else:
        bearish.append("short momentum is contracting")
    if market.rsi_14 < 32:
        bullish.append("RSI is in an oversold region")
    elif market.rsi_14 > 70:
        bearish.append("RSI is in an overbought region")
    elif 45 <= market.rsi_14 <= 65:
        bullish.append("RSI supports constructive momentum")
    score = len(bullish) - len(bearish)
    return score, bullish, bearish


def _confidence_for(rating: str, market: MarketSnapshot) -> float:
    score, _, _ = _technical_score(market)
    direction = 1 if rating in {"Buy", "Overweight"} else -1 if rating in {"Sell", "Underweight"} else 0
    base = 66 if direction else 52
    agreement = score * direction * 5 if direction else -abs(score) * 2
    volatility_penalty = max(0, market.volatility_pct - 5) * 1.2
    return max(35, min(91, round(base + agreement - volatility_penalty, 1)))


class TradingAnalysisService:
    """Wrap TradingAgents and provide an explicit no-key demo fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._graph: Any | None = None
        self._graph_lock = threading.Lock()

    def analyze(self, symbol: str, market: MarketSnapshot) -> AnalysisResult:
        if self.settings.ai_configured:
            try:
                return self._analyze_with_tradingagents(symbol, market)
            except Exception as exc:
                if not self.settings.allow_demo_fallback:
                    raise RuntimeError(f"TradingAgents analysis failed: {exc}") from exc
                result = self._demo_analysis(symbol, market)
                result.reports["system_note"] = (
                    "TradingAgents could not complete this run, so the configured "
                    "deterministic fallback produced the decision. No order is presented "
                    "as an AI decision."
                )
                return result
        return self._demo_analysis(symbol, market)

    def _get_graph(self):
        if self._graph is not None:
            return self._graph
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise RuntimeError(
                "TradingAgents is not installed; run `pip install -e '.[ai]'`"
            ) from exc

        config = DEFAULT_CONFIG.copy()
        config.update(
            {
                "llm_provider": self.settings.llm_provider,
                "deep_think_llm": self.settings.deep_think_llm,
                "quick_think_llm": self.settings.quick_think_llm,
                "backend_url": self.settings.llm_backend_url,
                "max_debate_rounds": 1,
                "max_risk_discuss_rounds": 1,
                "checkpoint_enabled": True,
                "results_dir": str(self.settings.data_dir / "tradingagents-results"),
                "data_cache_dir": str(self.settings.data_dir / "tradingagents-cache"),
                "memory_log_path": str(self.settings.data_dir / "tradingagents-memory.md"),
                "benchmark_ticker": "BTC-USD",
            }
        )
        self._graph = TradingAgentsGraph(
            selected_analysts=("market", "social", "news"),
            debug=False,
            config=config,
        )
        return self._graph

    def _analyze_with_tradingagents(
        self, symbol: str, market: MarketSnapshot
    ) -> AnalysisResult:
        yahoo_symbol = yahoo_crypto_symbol(symbol, self.settings.quote_asset)
        with self._graph_lock:
            graph = self._get_graph()
            state, raw_rating = graph.propagate(
                yahoo_symbol,
                datetime.now(UTC).date().isoformat(),
                asset_type="crypto",
            )
        rating = str(raw_rating).title()
        if rating not in _ALLOWED_RATINGS:
            rating = "Hold"
        final_decision = str(state.get("final_trade_decision", ""))
        summary = self._extract_summary(final_decision) or (
            f"The TradingAgents portfolio manager returned a {rating} rating for {yahoo_symbol}."
        )
        reports = {
            "market_analyst": str(state.get("market_report", "")),
            "sentiment_analyst": str(state.get("sentiment_report", "")),
            "news_analyst": str(state.get("news_report", "")),
            "bull_bear_research": str(state.get("investment_plan", "")),
            "trader": str(state.get("trader_investment_plan", "")),
            "risk_team": str(state.get("risk_debate_state", {}).get("judge_decision", "")),
            "portfolio_manager": final_decision,
        }
        return AnalysisResult(
            rating=rating,  # type: ignore[arg-type]
            confidence=_confidence_for(rating, market),
            summary=summary,
            source="tradingagents",
            reports=reports,
        )

    @staticmethod
    def _extract_summary(decision: str) -> str:
        match = re.search(
            r"\*\*Executive Summary\*\*:\s*(.+?)(?:\n\s*\n|\*\*Investment Thesis)",
            decision,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return " ".join(match.group(1).split()) if match else ""

    @staticmethod
    def _demo_analysis(symbol: str, market: MarketSnapshot) -> AnalysisResult:
        score, bullish, bearish = _technical_score(market)
        if score >= 3:
            rating: Rating = "Buy"
        elif score == 2:
            rating = "Overweight"
        elif score <= -3:
            rating = "Sell"
        elif score == -2:
            rating = "Underweight"
        else:
            rating = "Hold"
        confidence = min(88, 54 + abs(score) * 8)
        balance = (
            f"{len(bullish)} constructive signals versus {len(bearish)} caution signals"
        )
        summary = (
            f"Deterministic demo consensus is {rating.lower()} for {symbol}: {balance}. "
            f"RSI is {market.rsi_14:.1f}, 24-hour change is {market.change_24h_pct:+.2f}%, "
            f"and realized volatility is {market.volatility_pct:.2f}%."
        )
        market_report = "\n".join(
            [
                "## Technical market analyst",
                f"- Last price: {market.price:,.4f}",
                f"- RSI (14): {market.rsi_14:.1f}",
                f"- SMA 20 / SMA 50: {market.sma_20:,.4f} / {market.sma_50:,.4f}",
                f"- EMA 12 / EMA 26: {market.ema_12:,.4f} / {market.ema_26:,.4f}",
                f"- Constructive: {', '.join(bullish) or 'none'}.",
                f"- Caution: {', '.join(bearish) or 'none'}.",
            ]
        )
        return AnalysisResult(
            rating=rating,
            confidence=confidence,
            summary=summary,
            source="demo",
            reports={
                "market_analyst": market_report,
                "sentiment_analyst": (
                    "Demo mode does not fabricate social sentiment. Configure an LLM provider "
                    "to activate the TradingAgents sentiment analyst."
                ),
                "news_analyst": (
                    "Demo mode does not fabricate news. Configure TradingAgents for sourced "
                    "news and macro analysis."
                ),
                "bull_bear_research": (
                    f"Bull case: {', '.join(bullish) or 'limited confirmation'}.\n\n"
                    f"Bear case: {', '.join(bearish) or 'limited confirmation'}."
                ),
                "risk_team": (
                    f"Volatility is {market.volatility_pct:.2f}%. Apply the configured hard "
                    "position cap and stop distance before considering execution."
                ),
                "portfolio_manager": f"**Rating**: {rating}\n\n**Executive Summary**: {summary}",
            },
        )
