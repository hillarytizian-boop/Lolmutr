"""Account snapshot: paper wallet in DEMO, signed Binance account in LIVE."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from app.binance.client import BinanceError, BinanceSigned
from app.binance.feed import MarketFeed
from app.binance.paper import PaperBroker
from app.config import get_settings, missing_credentials

logger = logging.getLogger("trading")


@dataclass
class AccountSnapshot:
    mode: str
    wallet_balance: float
    available: float
    equity: float
    used_margin: float
    free_margin: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    daily_pnl_pct: float
    total_pnl: float
    total_pnl_pct: float
    cash: float
    positions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    connected: bool = False
    auth: str = "NONE"
    auth_detail: str = ""
    source: str = "paper"
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _from_paper(snap: dict[str, Any], *, start_equity: float | None) -> AccountSnapshot:
    equity = float(snap.get("equity") or 0)
    cash = float(snap.get("cash") or 0)
    start = float(start_equity or snap.get("starting_cash") or equity or 1)
    total = float(snap.get("pnl") or (equity - start))
    used = max(0.0, equity - cash)
    return AccountSnapshot(
        mode="DEMO",
        wallet_balance=equity,
        available=cash,
        equity=equity,
        used_margin=used,
        free_margin=cash,
        unrealized_pnl=float(snap.get("unrealized_pnl") or 0),
        realized_pnl=float(snap.get("realized_pnl") or 0),
        daily_pnl=0.0,
        daily_pnl_pct=0.0,
        total_pnl=total,
        total_pnl_pct=float(snap.get("pnl_pct") or 0),
        cash=cash,
        positions=list(snap.get("positions") or []),
        orders=list(snap.get("orders") or []),
        connected=True,
        auth="NOT_REQUIRED",
        auth_detail="paper wallet",
        source="paper",
    )


def fetch_account(
    *,
    broker: PaperBroker,
    feed: MarketFeed,
    marks: dict[str, float] | None = None,
    start_equity: float | None = None,
) -> AccountSnapshot:
    settings = get_settings()
    missing = missing_credentials(settings)
    if not settings.signed_ready:
        paper = broker.snapshot(marks or {})
        snap = _from_paper(paper, start_equity=start_equity)
        if settings.trading_mode == "live" and missing:
            snap.auth = "FAILED"
            snap.auth_detail = "Missing: " + ", ".join(missing)
            snap.missing = missing
        return snap

    try:
        signed = BinanceSigned()
        raw = signed.account()
        open_orders = signed.open_orders()
    except BinanceError as exc:
        logger.error("signed account failed: %s", exc)
        paper = broker.snapshot(marks or {})
        snap = _from_paper(paper, start_equity=start_equity)
        snap.auth = "FAILED"
        snap.auth_detail = str(exc)[:180]
        snap.connected = False
        snap.mode = settings.display_mode
        return snap

    usdt_free = usdt_locked = 0.0
    others: list[tuple[str, float, float]] = []
    for bal in raw.get("balances") or []:
        asset = bal.get("asset") or ""
        free = float(bal.get("free") or 0)
        locked = float(bal.get("locked") or 0)
        if asset == "USDT":
            usdt_free = free
            usdt_locked = locked
            continue
        if free + locked <= 0:
            continue
        others.append((asset, free, locked))

    positions: list[dict[str, Any]] = []
    unrealized = 0.0
    used = usdt_locked
    for asset, free, locked in others:
        qty = free + locked
        symbol = f"{asset}USDT"
        mark = (marks or {}).get(symbol)
        if mark is None:
            try:
                mark = feed.price(symbol)
            except Exception:
                continue
        notional = mark * qty
        used += notional
        positions.append(
            {
                "symbol": symbol,
                "qty": qty,
                "avg_price": mark,
                "mark": mark,
                "notional": notional,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "free": free,
                "locked": locked,
            }
        )

    equity = usdt_free + usdt_locked + sum(p["notional"] for p in positions)
    start = float(start_equity or equity)
    total = equity - start
    return AccountSnapshot(
        mode=settings.display_mode,
        wallet_balance=equity,
        available=usdt_free,
        equity=equity,
        used_margin=used,
        free_margin=usdt_free,
        unrealized_pnl=unrealized,
        realized_pnl=0.0,
        daily_pnl=0.0,
        daily_pnl_pct=0.0,
        total_pnl=total,
        total_pnl_pct=(total / start * 100.0) if start else 0.0,
        cash=usdt_free,
        positions=positions,
        orders=open_orders,
        connected=True,
        auth="OK",
        auth_detail="signed account",
        source="binance",
    )
