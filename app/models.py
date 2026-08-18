"""Shared dataclasses that travel between the desk, the agents, and the API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
ACTIONS = ("Buy", "Hold", "Sell")


def rating_to_action(rating: str) -> str:
    if rating in ("Buy", "Overweight"):
        return "Buy"
    if rating in ("Sell", "Underweight"):
        return "Sell"
    return "Hold"


def rating_size_pct(rating: str, volatility_adj: float = 1.0) -> float:
    """Suggested notional as a fraction of equity, after a vol haircut."""
    base = {
        "Buy": 0.10,
        "Overweight": 0.05,
        "Hold": 0.0,
        "Underweight": 0.0,
        "Sell": 0.0,
    }.get(rating, 0.0)
    adj = max(0.35, min(1.25, volatility_adj))
    return round(base * adj, 4)


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Indicators:
    last_close: float
    change_24h: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    ema20: float
    ema50: float
    sma20: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    atr: float
    atr_pct: float
    volume: float
    volume_sma: float
    high_20: float
    low_20: float
    stoch_k: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentReport:
    name: str
    role: str
    stance: str
    score: float
    confidence: str
    summary: str
    details: str
    signals: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    rating: str
    action: str
    score: float
    confidence: float
    size_pct: float
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    time_horizon: str
    executive_summary: str
    thesis: str
    engine: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisRun:
    id: str
    symbol: str
    interval: str
    created_at: str
    price: float
    indicators: dict[str, Any]
    reports: list[dict[str, Any]]
    debate: list[dict[str, Any]]
    decision: dict[str, Any]
    order: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
