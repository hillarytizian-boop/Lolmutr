"""Normalized decision contract. Values come from TradingAgents or are labeled."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_ACTIONS = ("BUY", "SELL", "HOLD")
VALID_STATUSES = (
    "ANALYSIS_FAILED",
    "HOLD",
    "BUY",
    "SELL",
    "RISK_REJECTED",
    "EXECUTION_FAILED",
    "EXECUTED",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TradeDecision:
    symbol: str
    action: str  # BUY | SELL | HOLD
    confidence: float
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    position_size: float
    risk_reward: float | None
    thesis: str
    bull_case: str
    bear_case: str
    risk_assessment: str
    portfolio_decision: str
    timestamp: str
    brain: str
    cycle_id: str
    rating: str = "Hold"
    yahoo_symbol: str = ""
    stages: dict[str, str] = field(default_factory=dict)
    reports: dict[str, str] = field(default_factory=dict)
    risk_source: str = "tradingagents"
    brain_online: bool = False
    error: str | None = None
    status: str = "HOLD"
    confidence_provided: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def hold(
        cls,
        symbol: str,
        thesis: str,
        *,
        cycle_id: str,
        confidence: float = 0.0,
        error: str | None = None,
        brain_online: bool = False,
        reports: dict[str, str] | None = None,
        stages: dict[str, str] | None = None,
        status: str = "HOLD",
        confidence_provided: bool = False,
    ) -> TradeDecision:
        return cls(
            symbol=symbol,
            action="HOLD",
            confidence=confidence,
            entry=None,
            stop_loss=None,
            take_profit=[],
            position_size=0.0,
            risk_reward=None,
            thesis=thesis,
            bull_case="",
            bear_case="",
            risk_assessment="",
            portfolio_decision=thesis,
            timestamp=_now(),
            brain="TradingAgents",
            cycle_id=cycle_id,
            rating="Hold",
            reports=reports or {},
            stages=stages or {},
            risk_source="none",
            brain_online=brain_online,
            error=error,
            status=status,
            confidence_provided=confidence_provided,
            reason=thesis,
        )

    @classmethod
    def failed(
        cls,
        symbol: str,
        reason: str,
        *,
        cycle_id: str,
        reports: dict[str, str] | None = None,
        stages: dict[str, str] | None = None,
    ) -> TradeDecision:
        thesis = f"ANALYSIS FAILED: {reason}"
        return cls.hold(
            symbol,
            thesis,
            cycle_id=cycle_id,
            error=reason,
            brain_online=False,
            reports=reports,
            stages=stages,
            status="ANALYSIS_FAILED",
        )
