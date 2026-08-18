from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Candle(BaseModel):
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketSnapshot(BaseModel):
    symbol: str
    price: float
    change_24h_pct: float
    high_24h: float
    low_24h: float
    volume_24h: float
    quote_volume_24h: float
    rsi_14: float
    sma_20: float
    sma_50: float
    ema_12: float
    ema_26: float
    volatility_pct: float
    data_source: Literal["binance", "synthetic"] = "binance"
    updated_at: datetime
    candles: list[Candle] = Field(default_factory=list)


Rating = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]


class AnalysisResult(BaseModel):
    rating: Rating
    confidence: float = Field(ge=0, le=100)
    summary: str
    source: Literal["tradingagents", "demo"]
    reports: dict[str, str] = Field(default_factory=dict)


class TradePlan(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    executable: bool
    reason: str
    quantity: float = 0
    notional: float = 0
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_amount: float = 0


class OrderRecord(BaseModel):
    id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: float
    notional: float
    fee: float
    status: str
    mode: str
    external_id: str | None = None
    created_at: datetime


class Balance(BaseModel):
    asset: str
    free: float
    locked: float = 0
    value_quote: float = 0


class Portfolio(BaseModel):
    quote_asset: str
    total_equity: float
    available_cash: float
    invested_value: float
    balances: list[Balance]
    recent_orders: list[OrderRecord]


class RunRequest(BaseModel):
    symbol: str
    execute: bool = False
    confirmation: str | None = None


class RunRecord(BaseModel):
    id: str
    symbol: str
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    execute_requested: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentStatus(BaseModel):
    mode: str
    intelligence: str
    broker_connected: bool
    execution_enabled: bool
    control_auth_required: bool
    auto_trading_enabled: bool
    auto_execute: bool
    interval_minutes: int
    symbols: list[str]
    quote_asset: str
    risk_per_trade_pct: float
    max_position_pct: float
    min_confidence: float
    stop_loss_pct: float
    take_profit_pct: float
    safety_message: str
