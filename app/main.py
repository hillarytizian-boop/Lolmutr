"""FastAPI desk — live Binance data + TradingAgents-style firm."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agents.context import fetch_fear_greed, fetch_news
from app.agents.graph import TradingDesk
from app.agents.llm_bridge import probe
from app.binance.client import BinanceError
from app.binance.feed import MarketFeed
from app.binance.paper import PaperBroker
from app.binance.symbols import to_binance
from app.config import DEFAULT_WATCHLIST, get_settings
from app.store import RunStore

WEB = Path(__file__).resolve().parent.parent / "web"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

settings = get_settings()
public = MarketFeed()
broker = PaperBroker()
store = RunStore()
desk = TradingDesk(public=public, broker=broker)

app = FastAPI(title="Lolmutr", version="1.0.0", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")
if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


class AnalyzeRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    execute: bool = False


class OrderRequest(BaseModel):
    symbol: str
    side: str
    notional: float | None = None
    quantity: float | None = None


class SettingsUpdate(BaseModel):
    # Public knobs only — API secrets stay in the environment.
    watchlist: list[str] | None = None
    default_interval: str | None = Field(default=None, max_length=8)


@app.get("/")
def index() -> FileResponse:
    page = WEB / "index.html"
    if not page.exists():
        raise HTTPException(404, "dashboard missing")
    return FileResponse(page)


@app.get("/api/health")
def health() -> dict[str, Any]:
    binance_ok = False
    try:
        binance_ok = public.ping()
    except BinanceError:
        binance_ok = False
    return {
        "ok": True,
        "binance": binance_ok,
        "feed": public.source,
        "mode": settings.trading_mode,
        "signed_ready": settings.signed_ready,
        **probe(),
    }


@app.get("/api/config")
def config() -> dict[str, Any]:
    s = get_settings()
    return {
        "mode": s.trading_mode,
        "feed": public.source,
        "signed_ready": s.signed_ready,
        "live_unlocked": s.live_unlocked,
        "watchlist": list(DEFAULT_WATCHLIST),
        "paper_starting_cash": s.paper_starting_cash,
        **probe(),
    }


@app.get("/api/markets")
def markets(limit: int = 12) -> list[dict[str, Any]]:
    try:
        rows = public.tickers(list(DEFAULT_WATCHLIST))
    except BinanceError as exc:
        raise HTTPException(502, str(exc)) from exc
    return rows[:limit]


@app.get("/api/ticker/{symbol}")
def ticker(symbol: str) -> dict[str, Any]:
    try:
        return public.ticker(symbol)
    except (BinanceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/klines/{symbol}")
def klines(symbol: str, interval: str = "1h", limit: int = 200) -> list[dict[str, Any]]:
    try:
        rows = public.klines(symbol, interval=interval, limit=min(limit, 500))
    except (BinanceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return [c.to_dict() for c in rows]


@app.get("/api/depth/{symbol}")
def depth(symbol: str) -> dict[str, Any]:
    try:
        return public.depth(symbol)
    except (BinanceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/news")
def news() -> dict[str, Any]:
    return {"fear_greed": fetch_fear_greed(), "headlines": fetch_news()}


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict[str, Any]:
    try:
        pair = to_binance(req.symbol)
        result = desk.analyze(pair, interval=req.interval, execute=req.execute)
    except (BinanceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    store.add(result)
    return result


@app.get("/api/runs")
def runs(limit: int = 20) -> list[dict[str, Any]]:
    return store.list(limit=limit)


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    row = store.get(run_id)
    if not row:
        raise HTTPException(404, "run not found")
    return row


@app.get("/api/portfolio")
def portfolio() -> dict[str, Any]:
    marks: dict[str, float] = {}
    snap = broker.snapshot()
    for pos in snap["positions"]:
        try:
            marks[pos["symbol"]] = public.price(pos["symbol"])
        except BinanceError:
            continue
    return broker.snapshot(marks)


@app.post("/api/portfolio/reset")
def reset_portfolio() -> dict[str, Any]:
    return broker.reset()


@app.post("/api/orders")
def place_order(req: OrderRequest) -> dict[str, Any]:
    try:
        pair = to_binance(req.symbol)
        price = public.price(pair)
        order = broker.market_order(
            pair,
            req.side,
            quantity=req.quantity,
            notional=req.notional,
            price=price,
            reason="manual",
        )
    except (BinanceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return order


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    run()
