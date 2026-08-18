"""Run the official TradingAgents desk seats against NVIDIA GLM-5.2.

Prompts are taken from TauricResearch/TradingAgents (GitHub). Signals come
only from the Portfolio Manager seat. This is not a one-shot BUY/SELL model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from app.llm import complete, parse_llm_rating
from brain.decision import TradeDecision
from brain.ta_source import official_parse_rating, official_root
from brain.tradingagents_brain import STAGES, _RATING_TO_ACTION

logger = logging.getLogger("tradingagents")

# Official seat prompts — TauricResearch/TradingAgents agents/*.py
_MARKET = (
    "You are a trading assistant tasked with analyzing financial markets. "
    "Write a detailed report of the trends you observe from the tape provided. "
    "Do not invent prices that are not in the tape. Append a Markdown table."
)
_SENTIMENT = (
    "You are the TradingAgents Sentiment Analyst. If sentiment data is marked "
    "unavailable, say so. Do not fabricate Fear & Greed or headlines."
)
_NEWS = (
    "You are the TradingAgents News Analyst. If the wire is empty, say the "
    "wire is empty. Do not invent headlines."
)
_BULL = (
    "You are a Bull Analyst advocating for investing in the asset. Build an "
    "evidence-based case from the research only. Address bear concerns. "
    "Do not invent data."
)
_BEAR = (
    "You are a Bear Analyst arguing against investing in the asset. Build an "
    "evidence-based cautious case from the research only. Do not invent data."
)
_RM = (
    "As the Research Manager and debate facilitator, critically evaluate this "
    "round of debate and deliver a clear investment plan. Rating scale: "
    "Buy / Overweight / Hold / Underweight / Sell. Reserve Hold when evidence "
    "is genuinely balanced."
)
_TRADER = (
    "You are a trading agent analyzing market data to make investment decisions. "
    "Provide a specific recommendation to buy, sell, or hold. Anchor reasoning "
    "in the analysts' reports and the research plan. "
    "End with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**."
)
_RISK = (
    "As the Conservative Risk Analyst, protect assets and minimize volatility. "
    "Critically examine the trader's decision. You may force Hold. "
    "Do not invent numbers."
)
_PM = (
    "As the Portfolio Manager, synthesize the risk analysts' debate and deliver "
    "the final trading decision. Rating scale (exactly one): Buy, Overweight, "
    "Hold, Underweight, Sell. Reply with JSON only: "
    '{"rating":"Buy|Overweight|Hold|Underweight|Sell","confidence":0.0,'
    '"thesis":"two sentences"}. Hold is correct when there is no edge. '
    "Do not force a trade. Do not invent prices."
)


def run_firm(
    symbol: str,
    *,
    cycle_id: str,
    market_blob: str,
    on_stage: Callable[[str, str], None] | None = None,
) -> TradeDecision:
    def stage(name: str, status: str) -> None:
        if on_stage:
            on_stage(name, status)

    src = official_root()
    source_note = (
        f"source={src}" if src else "source=https://github.com/TauricResearch/TradingAgents"
    )
    logger.info("%s TradingAgents seats start %s", cycle_id, source_note)

    for name in STAGES:
        stage(name, "PENDING")

    reports: dict[str, str] = {}
    tape = f"Instrument {symbol} (crypto spot).\n{market_blob}"

    def seat(name: str, system: str, user: str) -> str:
        stage(name, "RUNNING")
        text = complete(system, user, timeout=90.0) or ""
        stage(name, "COMPLETE")
        return text

    reports["market"] = seat("market", _MARKET, tape)
    reports["sentiment"] = seat(
        "sentiment", _SENTIMENT, tape + "\nMarket report:\n" + reports["market"]
    )
    reports["news"] = seat("news", _NEWS, tape + "\nSentiment:\n" + reports["sentiment"])
    stage("fundamentals", "SKIPPED")
    book = (
        f"Market research report: {reports['market']}\n"
        f"Social media sentiment report: {reports['sentiment']}\n"
        f"Latest world affairs news: {reports['news']}\n"
        "Asset fundamentals report (may be unavailable for crypto): n/a"
    )
    reports["bull"] = seat("bull", _BULL, book)
    reports["bear"] = seat("bear", _BEAR, book + "\nLast bull argument:\n" + reports["bull"])
    debate = f"Bull:\n{reports['bull']}\n\nBear:\n{reports['bear']}"
    reports["plan"] = seat("trader", _RM, "**Debate History:**\n" + debate)
    reports["trader"] = seat(
        "trader",
        _TRADER,
        f"Proposed Investment Plan: {reports['plan']}\n\n{book}",
    )
    reports["risk"] = seat("risk", _RISK, f"Trader decision:\n{reports['trader']}\n{book}")
    reports["final"] = seat(
        "portfolio",
        _PM,
        f"Research plan: {reports['plan']}\nTrader: {reports['trader']}\n"
        f"Risk: {reports['risk']}",
    )

    parse = official_parse_rating()
    rating = parse(reports["final"] or "")
    if rating == "Hold":
        parsed = parse_llm_rating(reports["final"] or "")
        if parsed:
            rating = parsed["rating"]
            conf = parsed.get("confidence") or 0.0
            thesis = parsed.get("thesis") or reports["final"]
        else:
            conf = 0.0
            thesis = reports["final"] or "Portfolio Manager stayed flat."
    else:
        parsed = parse_llm_rating(reports["final"] or "")
        conf = (parsed or {}).get("confidence") or 0.0
        thesis = (parsed or {}).get("thesis") or reports["final"]

    action = _RATING_TO_ACTION.get(str(rating).lower(), "HOLD")
    logger.info("%s Portfolio Manager decision: %s", cycle_id, rating)
    return TradeDecision(
        symbol=symbol,
        action=action,
        confidence=float(conf or 0.0),
        entry=None,
        stop_loss=None,
        take_profit=[],
        position_size=0.0,
        risk_reward=None,
        thesis=(thesis or "")[:4000],
        bull_case=reports.get("bull", "")[:2000],
        bear_case=reports.get("bear", "")[:2000],
        risk_assessment=reports.get("risk", "")[:2000],
        portfolio_decision=reports.get("final", "")[:2000],
        timestamp=datetime.now(timezone.utc).isoformat(),
        brain="TradingAgents",
        cycle_id=cycle_id,
        rating=str(rating),
        reports=reports,
        stages={n: "SKIPPED" if n == "fundamentals" else "COMPLETE" for n in STAGES},
        risk_source="none",
        brain_online=True,
    )
