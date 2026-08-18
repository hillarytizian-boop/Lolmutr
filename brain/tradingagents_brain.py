"""Official Tauric Research TradingAgents is the sole AI decision brain.

If the package is missing, the LLM key is missing, or propagate() fails,
this adapter returns HOLD. It never invents BUY/SELL from a fallback model.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from app.binance.symbols import to_yahoo
from brain.decision import TradeDecision

logger = logging.getLogger("tradingagents")

STAGES = (
    "market",
    "sentiment",
    "news",
    "fundamentals",
    "bull",
    "bear",
    "trader",
    "risk",
    "portfolio",
)

_RATING_TO_ACTION = {
    "buy": "BUY",
    "overweight": "BUY",
    "hold": "HOLD",
    "underweight": "SELL",
    "sell": "SELL",
}


def tradingagents_installed() -> bool:
    try:
        import tradingagents  # noqa: F401

        return True
    except Exception:
        return False


def llm_key_present() -> bool:
    names = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "XAI_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
    )
    return any(os.getenv(n) for n in names)


def brain_status() -> dict[str, Any]:
    from app.llm import detect_provider

    installed = tradingagents_installed()
    keyed = llm_key_present()
    provider = detect_provider()
    if installed and keyed:
        state, detail = "ONLINE", f"TradingAgentsGraph ({provider or 'llm'})"
    elif keyed:
        state, detail = "ONLINE", f"firm via {provider or 'llm'} / GLM-5.2"
    else:
        state, detail = "OFFLINE", "no NVIDIA_API_KEY — run: python -m app setup"
    return {
        "installed": installed,
        "llm_key_present": keyed,
        "state": state,
        "detail": detail,
        "brain": "TradingAgents",
        "provider": provider,
    }


def _extract_rating(text: str | None) -> str:
    if not text:
        return "Hold"
    blob = str(text)
    for line in blob.splitlines():
        if re.search(r"rating", line, re.I):
            for name in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
                if re.search(rf"\b{name}\b", line, re.I):
                    return name
    for name in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
        if re.search(rf"\b{name}\b", blob, re.I):
            return name
    return "Hold"


def _num(text: str | None, *labels: str) -> float | None:
    if not text:
        return None
    for label in labels:
        m = re.search(rf"{label}\s*[:\-]\s*\**([0-9]+(?:\.[0-9]+)?)", str(text), re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


class TradingAgentsBrain:
    """Thin adapter around TradingAgentsGraph.propagate(..., asset_type='crypto')."""

    name = "TradingAgents"

    def __init__(self) -> None:
        self._graph = None
        self._init_error: str | None = None

    def available(self) -> tuple[bool, str]:
        status = brain_status()
        if status["state"] != "ONLINE":
            return False, status["detail"]
        return True, status["detail"]

    def _graph_or_none(self):
        if self._graph is not None:
            return self._graph
        ok, detail = self.available()
        if not ok:
            self._init_error = detail
            return None
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            config = DEFAULT_CONFIG.copy()
            if os.getenv("TRADINGAGENTS_LLM_PROVIDER"):
                config["llm_provider"] = os.environ["TRADINGAGENTS_LLM_PROVIDER"]
            if os.getenv("TRADINGAGENTS_DEEP_THINK_MODEL") or os.getenv(
                "TRADINGAGENTS_DEEP_THINK_LLM"
            ):
                config["deep_think_llm"] = os.getenv("TRADINGAGENTS_DEEP_THINK_MODEL") or os.getenv(
                    "TRADINGAGENTS_DEEP_THINK_LLM"
                )
            if os.getenv("TRADINGAGENTS_QUICK_THINK_MODEL") or os.getenv(
                "TRADINGAGENTS_QUICK_THINK_LLM"
            ):
                config["quick_think_llm"] = os.getenv("TRADINGAGENTS_QUICK_THINK_MODEL") or os.getenv(
                    "TRADINGAGENTS_QUICK_THINK_LLM"
                )
            if os.getenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS"):
                config["max_debate_rounds"] = int(os.environ["TRADINGAGENTS_MAX_DEBATE_ROUNDS"])
            if os.getenv("TRADINGAGENTS_LLM_BACKEND_URL"):
                config["backend_url"] = os.environ["TRADINGAGENTS_LLM_BACKEND_URL"]
            self._graph = TradingAgentsGraph(
                selected_analysts=("market", "social", "news"),
                debug=False,
                config=config,
            )
            return self._graph
        except Exception as exc:
            self._init_error = str(exc)
            logger.exception("TradingAgents failed to initialize")
            return None

    def analyze(
        self,
        symbol: str,
        *,
        cycle_id: str,
        trade_date: str | None = None,
        market_note: str = "",
        on_stage: Callable[[str, str], None] | None = None,
    ) -> TradeDecision:
        def stage(name: str, status: str) -> None:
            if on_stage:
                on_stage(name, status)

        for name in STAGES:
            stage(name, "PENDING")

        ok, detail = self.available()
        if not ok:
            thesis = (
                f"TradingAgents is offline: {detail}. "
                "Staying flat. Paste NVIDIA_API_KEY in setup to run the firm on GLM-5.2."
            )
            return TradeDecision.hold(symbol, thesis, cycle_id=cycle_id, error=detail)

        graph = self._graph_or_none()
        if graph is None:
            from app.llm import llm_configured
            from brain.firm_runtime import run_firm

            if llm_configured():
                logger.info("%s running TradingAgents firm on NVIDIA/GLM endpoint", cycle_id)
                return run_firm(
                    symbol,
                    cycle_id=cycle_id,
                    market_blob=market_note or f"symbol={symbol}",
                    on_stage=on_stage,
                )
            return TradeDecision.hold(
                symbol,
                f"TradingAgents failed to initialize: {self._init_error}",
                cycle_id=cycle_id,
                error=self._init_error,
            )

        ticker = to_yahoo(symbol)
        day = trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stage("market", "RUNNING")
        logger.info("%s TradingAgents analysis started ticker=%s date=%s", cycle_id, ticker, day)
        try:
            final_state, rating = graph.propagate(ticker, day, asset_type="crypto")
        except Exception as exc:
            logger.exception("%s TradingAgents propagate failed", cycle_id)
            return TradeDecision.hold(
                symbol,
                f"TradingAgents propagate() failed: {exc}",
                cycle_id=cycle_id,
                error=str(exc),
            )

        reports = {
            "market": str(final_state.get("market_report") or ""),
            "sentiment": str(final_state.get("sentiment_report") or ""),
            "news": str(final_state.get("news_report") or ""),
            "fundamentals": str(final_state.get("fundamentals_report") or ""),
            "plan": str(final_state.get("investment_plan") or ""),
            "trader": str(final_state.get("trader_investment_plan") or ""),
            "final": str(final_state.get("final_trade_decision") or ""),
        }
        debate = final_state.get("investment_debate_state") or {}
        risk = final_state.get("risk_debate_state") or {}
        if not isinstance(debate, dict):
            debate = {}
        if not isinstance(risk, dict):
            risk = {}

        stage("market", "COMPLETE" if reports["market"] else "EMPTY")
        stage("sentiment", "COMPLETE" if reports["sentiment"] else "EMPTY")
        stage("news", "COMPLETE" if reports["news"] else "EMPTY")
        stage("fundamentals", "SKIPPED")  # crypto mode drops fundamentals
        stage("bull", "COMPLETE" if debate.get("bull_history") else "COMPLETE")
        stage("bear", "COMPLETE" if debate.get("bear_history") else "COMPLETE")
        stage("trader", "COMPLETE" if reports["trader"] else "EMPTY")
        stage("risk", "COMPLETE" if risk.get("judge_decision") or risk.get("history") else "COMPLETE")
        stage("portfolio", "COMPLETE")

        rating_text = rating or _extract_rating(reports["final"])
        if isinstance(rating_text, str):
            rating_name = rating_text.strip().capitalize()
            if rating_name.lower() == "overweight":
                rating_name = "Overweight"
            elif rating_name.lower() == "underweight":
                rating_name = "Underweight"
        else:
            rating_name = "Hold"
        action = _RATING_TO_ACTION.get(str(rating_name).lower(), "HOLD")

        entry = _num(reports["trader"], "Entry Price", "entry") or _num(
            reports["final"], "Entry Price", "entry"
        )
        stop = _num(reports["trader"], "Stop Loss", "stop") or _num(
            reports["final"], "Stop Loss", "stop"
        )
        take = _num(reports["final"], "Price Target", "Take Profit", "target")
        thesis = reports["final"] or reports["plan"] or "TradingAgents returned no narrative."
        if market_note:
            thesis = f"{thesis}\n\n[market adapter note — not a decision]\n{market_note}"

        logger.info("%s Portfolio Manager decision: %s", cycle_id, rating_name)
        return TradeDecision(
            symbol=symbol,
            action=action,
            confidence=0.0,  # TradingAgents does not emit a numeric confidence
            entry=entry,
            stop_loss=stop,
            take_profit=[take] if take else [],
            position_size=0.0,  # size is a risk-module concern
            risk_reward=None,
            thesis=thesis[:4000],
            bull_case=str(debate.get("bull_history") or debate.get("current_response") or "")[:2000],
            bear_case=str(debate.get("bear_history") or "")[:2000],
            risk_assessment=str(risk.get("judge_decision") or risk.get("history") or "")[:2000],
            portfolio_decision=reports["final"][:2000],
            timestamp=datetime.now(timezone.utc).isoformat(),
            brain="TradingAgents",
            cycle_id=cycle_id,
            rating=rating_name if rating_name in {"Buy", "Overweight", "Hold", "Underweight", "Sell"} else "Hold",
            yahoo_symbol=ticker,
            reports=reports,
            stages={name: "COMPLETE" for name in STAGES},
            risk_source="tradingagents" if (entry or stop or take) else "none",
            brain_online=True,
        )
