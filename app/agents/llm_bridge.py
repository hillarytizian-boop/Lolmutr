"""Optional hook into the official Tauric Research TradingAgents graph.

The desk runs without this. When `tradingagents` is installed and an LLM
key is present, we also call `TradingAgentsGraph.propagate` in crypto mode
and fold the 5-tier rating into the Binance-native decision.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.binance.symbols import to_yahoo

logger = logging.getLogger(__name__)

_LLM_ENV = (
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVAPI_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
)


def llm_available() -> bool:
    return any(os.getenv(name) for name in _LLM_ENV)


def tradingagents_installed() -> bool:
    try:
        import tradingagents  # noqa: F401

        return True
    except Exception:
        return False


def probe() -> dict[str, Any]:
    return {
        "tradingagents_installed": tradingagents_installed(),
        "llm_key_present": llm_available(),
        "engine": (
            "tradingagents"
            if tradingagents_installed() and llm_available()
            else "binance-native"
        ),
    }


def run_tradingagents(symbol: str, trade_date: str | None = None) -> dict[str, Any] | None:
    """Run the official graph in crypto mode. Returns None if unavailable."""
    if not (tradingagents_installed() and llm_available()):
        return None
    ticker = to_yahoo(symbol)
    day = trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = DEFAULT_CONFIG.copy()
        config["max_debate_rounds"] = int(os.getenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS") or 1)
        config["max_risk_discuss_rounds"] = 1
        graph = TradingAgentsGraph(
            selected_analysts=("market", "social", "news"),
            debug=False,
            config=config,
        )
        final_state, rating = graph.propagate(ticker, day, asset_type="crypto")
        return {
            "ticker": ticker,
            "rating": rating,
            "final_trade_decision": final_state.get("final_trade_decision"),
            "market_report": final_state.get("market_report"),
            "sentiment_report": final_state.get("sentiment_report"),
            "news_report": final_state.get("news_report"),
            "investment_plan": final_state.get("investment_plan"),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
        }
    except Exception as exc:
        logger.warning("TradingAgents graph failed; continuing with native desk: %s", exc)
        return {"error": str(exc), "ticker": ticker}
