from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .analysis import TradingAnalysisService
from .broker import BinanceBroker, PaperBroker
from .config import Settings
from .market import BinanceAPIError, MarketDataClient
from .models import AgentStatus, Balance, Portfolio, RunRecord, RunRequest
from .orchestrator import AgentOrchestrator
from .risk import RiskEngine
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    store = Store(settings.db_path, settings.quote_asset, settings.paper_starting_balance)
    market = MarketDataClient(
        settings.public_market_url,
        settings.api_key,
        settings.api_secret,
        allow_synthetic=settings.mode == "paper",
    )
    broker = (
        PaperBroker(store, settings.quote_asset)
        if settings.mode == "paper"
        else BinanceBroker(market, store, settings.mode)
    )
    orchestrator = AgentOrchestrator(
        settings=settings,
        store=store,
        market=market,
        broker=broker,
        analysis=TradingAnalysisService(settings),
        risk=RiskEngine(settings),
    )
    app.state.settings = settings
    app.state.store = store
    app.state.market = market
    app.state.broker = broker
    app.state.orchestrator = orchestrator
    orchestrator.start_scheduler()
    logger.info(
        "Agent ready in %s mode with %s", settings.mode, settings.intelligence_mode
    )
    yield
    await orchestrator.shutdown()
    await market.close()
    store.close()


app = FastAPI(
    title="Binance Trading Agent",
    version="0.1.0",
    description="Safety-first Binance Spot execution with TradingAgents intelligence.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.exception_handler(BinanceAPIError)
async def binance_error_handler(_request: Request, exc: BinanceAPIError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
async def health(request: Request):
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "mode": settings.mode,
        "intelligence": settings.intelligence_mode,
    }


@app.get("/api/status", response_model=AgentStatus)
async def status(request: Request) -> AgentStatus:
    settings: Settings = request.app.state.settings
    if settings.mode == "paper":
        safety = "Simulated orders only — no Binance credentials are used"
        connected = True
    elif settings.mode == "testnet":
        safety = "Orders route to Binance Spot Testnet"
        connected = bool(settings.api_key and settings.api_secret)
    else:
        safety = (
            "Live orders are unlocked; each API request still requires an explicit phrase"
            if settings.live_trading_enabled
            else "Live market access only — order execution is locked"
        )
        connected = bool(settings.api_key and settings.api_secret)
    return AgentStatus(
        mode=settings.mode,
        intelligence=settings.intelligence_mode,
        broker_connected=connected,
        execution_enabled=(
            settings.mode in {"paper", "testnet"} or settings.live_trading_enabled
        ),
        control_auth_required=bool(settings.control_api_token),
        auto_trading_enabled=settings.auto_trading_enabled,
        auto_execute=settings.auto_execute,
        interval_minutes=settings.interval_minutes,
        symbols=list(settings.symbols),
        quote_asset=settings.quote_asset,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        max_position_pct=settings.max_position_pct,
        min_confidence=settings.min_confidence,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        safety_message=safety,
    )


@app.get("/api/market/{symbol}")
async def market_snapshot(symbol: str, request: Request):
    settings: Settings = request.app.state.settings
    symbol = symbol.upper()
    if symbol not in settings.symbols:
        raise HTTPException(status_code=404, detail="Symbol is not in the configured watchlist")
    snapshot = await request.app.state.market.snapshot(symbol)
    return snapshot


@app.get("/api/portfolio", response_model=Portfolio)
async def portfolio(request: Request) -> Portfolio:
    settings: Settings = request.app.state.settings
    raw_balances = await request.app.state.broker.balances()
    snapshots = await asyncio.gather(
        *(request.app.state.market.snapshot(symbol) for symbol in settings.symbols),
        return_exceptions=True,
    )
    prices: dict[str, float] = {}
    for symbol, snapshot in zip(settings.symbols, snapshots, strict=True):
        if not isinstance(snapshot, Exception):
            prices[symbol.removesuffix(settings.quote_asset)] = snapshot.price

    balances: list[Balance] = []
    invested = 0.0
    for asset, amounts in raw_balances.items():
        total = amounts.get("free", 0) + amounts.get("locked", 0)
        value = total if asset == settings.quote_asset else total * prices.get(asset, 0)
        if value or asset == settings.quote_asset:
            balances.append(
                Balance(
                    asset=asset,
                    free=amounts.get("free", 0),
                    locked=amounts.get("locked", 0),
                    value_quote=value,
                )
            )
            if asset != settings.quote_asset:
                invested += value
    cash = raw_balances.get(settings.quote_asset, {}).get("free", 0)
    return Portfolio(
        quote_asset=settings.quote_asset,
        total_equity=cash + invested,
        available_cash=cash,
        invested_value=invested,
        balances=sorted(balances, key=lambda item: item.value_quote, reverse=True),
        recent_orders=request.app.state.store.list_orders(12),
    )


def require_control_token(request: Request) -> None:
    """Protect state-changing endpoints when an operator token is configured."""
    expected = request.app.state.settings.control_api_token
    supplied = request.headers.get("X-Control-Token", "")
    if expected and not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="A valid control token is required")


@app.post("/api/runs", response_model=RunRecord, status_code=202)
async def create_run(payload: RunRequest, request: Request) -> RunRecord:
    require_control_token(request)
    try:
        return request.app.state.orchestrator.submit(
            payload.symbol,
            execute=payload.execute,
            confirmation=payload.confirmation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs", response_model=list[RunRecord])
async def list_runs(request: Request, limit: int = Query(12, ge=1, le=100)):
    return request.app.state.store.list_runs(limit)


@app.get("/api/runs/{run_id}", response_model=RunRecord)
async def get_run(run_id: str, request: Request):
    try:
        return request.app.state.store.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.post("/api/paper/reset")
async def reset_paper(request: Request):
    require_control_token(request)
    settings: Settings = request.app.state.settings
    if settings.mode != "paper":
        raise HTTPException(status_code=403, detail="Reset is only available in paper mode")
    request.app.state.store.reset_paper_account()
    return {"status": "reset", "balance": settings.paper_starting_balance}
