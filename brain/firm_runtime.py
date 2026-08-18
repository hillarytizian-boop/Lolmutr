"""TradingAgents firm on an OpenAI-compatible endpoint (NVIDIA GLM-5.2).

Used when the official `tradingagents` package cannot be installed (Termux
Python 3.14) but an LLM key is present. This is the same desk — analysts,
bull/bear debate, trader, risk, portfolio manager — not a one-shot BUY/SELL.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.llm import complete, parse_llm_rating
from brain.decision import TradeDecision
from brain.tradingagents_brain import STAGES, _RATING_TO_ACTION

logger = logging.getLogger("tradingagents")


def _ask(role: str, brief: str, payload: str) -> str:
    text = complete(brief, payload, timeout=90.0)
    return (text or "").strip()


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

    for name in STAGES:
        stage(name, "PENDING")

    reports: dict[str, str] = {}

    stage("market", "RUNNING")
    reports["market"] = _ask(
        "market",
        "You are the TradingAgents Market Analyst for crypto spot. "
        "Use only the numbers given. Do not invent prices. 6-10 sentences.",
        f"Instrument {symbol}. Tape:\n{market_blob}",
    ) or "Market analyst returned no text."
    stage("market", "COMPLETE")

    stage("sentiment", "RUNNING")
    reports["sentiment"] = _ask(
        "sentiment",
        "You are the TradingAgents Sentiment Analyst. If sentiment data is "
        "marked unavailable, say so. Do not fabricate Fear & Greed or headlines.",
        f"{symbol}\n{market_blob}\nMarket report:\n{reports['market']}",
    ) or "Sentiment unavailable."
    stage("sentiment", "COMPLETE")

    stage("news", "RUNNING")
    reports["news"] = _ask(
        "news",
        "You are the TradingAgents News Analyst. If the wire is empty, say the "
        "wire is empty. Do not invent headlines.",
        f"{symbol}\n{market_blob}\nSentiment:\n{reports['sentiment']}",
    ) or "News wire empty."
    stage("news", "COMPLETE")
    stage("fundamentals", "SKIPPED")

    book = (
        f"MARKET:\n{reports['market']}\n\nSENTIMENT:\n{reports['sentiment']}\n\n"
        f"NEWS:\n{reports['news']}"
    )

    stage("bull", "RUNNING")
    reports["bull"] = _ask(
        "bull",
        "You are the TradingAgents Bull Researcher. Argue the constructive case "
        "from the analyst book only. Do not invent data.",
        book,
    ) or ""
    stage("bull", "COMPLETE")

    stage("bear", "RUNNING")
    reports["bear"] = _ask(
        "bear",
        "You are the TradingAgents Bear Researcher. Argue the cautious case "
        "from the analyst book only. Do not invent data.",
        book + f"\n\nBULL:\n{reports['bull']}",
    ) or ""
    stage("bear", "COMPLETE")

    stage("trader", "RUNNING")
    reports["trader"] = _ask(
        "trader",
        "You are the TradingAgents Trader. Propose Buy, Hold, or Sell with "
        "entry/stop if you have numbers. JSON last line optional.",
        book + f"\n\nBULL:\n{reports['bull']}\n\nBEAR:\n{reports['bear']}",
    ) or ""
    stage("trader", "COMPLETE")

    stage("risk", "RUNNING")
    reports["risk"] = _ask(
        "risk",
        "You are the TradingAgents Risk committee (conservative chair). "
        "Haircut size if vol is high. You may force Hold.",
        f"TRADER:\n{reports['trader']}\n\n{book}",
    ) or ""
    stage("risk", "COMPLETE")

    stage("portfolio", "RUNNING")
    pm_text = _ask(
        "portfolio",
        "You are the TradingAgents Portfolio Manager. Final 5-tier rating. "
        "Reply with JSON only: "
        '{"rating":"Buy|Overweight|Hold|Underweight|Sell","confidence":0.0,'
        '"thesis":"two sentences"}. '
        "Hold is correct when the edge is not clear. Do not force a trade.",
        f"TRADER:\n{reports['trader']}\nRISK:\n{reports['risk']}\n{book}",
    )
    stage("portfolio", "COMPLETE")
    reports["final"] = pm_text or ""

    parsed = parse_llm_rating(pm_text or "")
    if not parsed:
        return TradeDecision.hold(
            symbol,
            "TradingAgents Portfolio Manager did not emit a parseable rating. Staying flat.",
            cycle_id=cycle_id,
            brain_online=True,
            reports=reports,
            stages={n: "COMPLETE" for n in STAGES},
        )

    rating = parsed["rating"]
    action = _RATING_TO_ACTION.get(rating.lower(), "HOLD")
    conf = parsed.get("confidence")
    if conf is None:
        conf = 0.0
    thesis = parsed.get("thesis") or reports["final"]
    logger.info("%s Portfolio Manager decision: %s", cycle_id, rating)
    return TradeDecision(
        symbol=symbol,
        action=action,
        confidence=float(conf),
        entry=None,
        stop_loss=None,
        take_profit=[],
        position_size=0.0,
        risk_reward=None,
        thesis=thesis[:4000],
        bull_case=reports.get("bull", "")[:2000],
        bear_case=reports.get("bear", "")[:2000],
        risk_assessment=reports.get("risk", "")[:2000],
        portfolio_decision=reports.get("final", "")[:2000],
        timestamp=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        brain="TradingAgents",
        cycle_id=cycle_id,
        rating=rating,
        reports=reports,
        stages={n: "COMPLETE" if n != "fundamentals" else "SKIPPED" for n in STAGES},
        risk_source="none",
        brain_online=True,
    )
