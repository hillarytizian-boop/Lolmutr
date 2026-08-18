from __future__ import annotations

import asyncio
import logging
from decimal import ROUND_DOWN, Decimal

from .analysis import TradingAnalysisService
from .broker import Broker
from .config import Settings
from .market import BinanceAPIError, MarketDataClient
from .models import RunRecord
from .risk import RiskEngine
from .storage import Store

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        store: Store,
        market: MarketDataClient,
        broker: Broker,
        analysis: TradingAnalysisService,
        risk: RiskEngine,
    ) -> None:
        self.settings = settings
        self.store = store
        self.market = market
        self.broker = broker
        self.analysis = analysis
        self.risk = risk
        self._locks = {symbol: asyncio.Lock() for symbol in settings.symbols}
        self._tasks: set[asyncio.Task] = set()
        self._scheduler_task: asyncio.Task | None = None

    def submit(
        self,
        symbol: str,
        *,
        execute: bool = False,
        confirmation: str | None = None,
        internal: bool = False,
    ) -> RunRecord:
        symbol = symbol.upper()
        if symbol not in self.settings.symbols:
            raise ValueError(f"{symbol} is not in the configured watchlist")
        if execute and self.settings.mode == "live":
            if not self.settings.live_trading_enabled:
                raise ValueError("Live execution is disabled by BINANCE_LIVE_TRADING")
            expected = f"EXECUTE {symbol}"
            if not internal and confirmation != expected:
                raise ValueError(f"Live execution requires confirmation: {expected}")
        run = self.store.create_run(symbol, execute)
        task = asyncio.create_task(self._run(run.id, symbol, execute))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run

    async def _run(self, run_id: str, symbol: str, execute: bool) -> None:
        async with self._locks[symbol]:
            try:
                self.store.update_run(
                    run_id, status="running", stage="Reading Binance market"
                )
                market = await self.market.snapshot(symbol)

                self.store.update_run(run_id, stage="Convening analyst team")
                analysis = await asyncio.to_thread(self.analysis.analyze, symbol, market)

                self.store.update_run(run_id, stage="Applying portfolio risk policy")
                balances = await self.broker.balances()
                plan = self.risk.build_plan(
                    symbol=symbol,
                    analysis=analysis,
                    market=market,
                    balances=balances,
                )
                order = None
                if execute and plan.executable:
                    self.store.update_run(run_id, stage="Validating Binance order filters")
                    plan.quantity = await self._valid_quantity(
                        symbol, plan.quantity, plan.entry_price
                    )
                    plan.notional = plan.quantity * plan.entry_price
                    if plan.quantity <= 0:
                        plan.executable = False
                        plan.action = "HOLD"
                        plan.reason = "Order size did not satisfy Binance symbol filters"
                    else:
                        self.store.update_run(run_id, stage=f"Executing {self.broker.mode} order")
                        order = await self.broker.market_order(
                            symbol=symbol,
                            side=plan.action,
                            quantity=plan.quantity,
                            reference_price=market.price,
                        )

                result = {
                    "market": market.model_dump(mode="json"),
                    "analysis": analysis.model_dump(mode="json"),
                    "plan": plan.model_dump(mode="json"),
                    "order": order.model_dump(mode="json") if order else None,
                    "execution_requested": execute,
                }
                self.store.update_run(
                    run_id,
                    status="completed",
                    stage="Complete",
                    result=result,
                )
            except Exception as exc:
                logger.exception("Agent run %s failed", run_id)
                self.store.update_run(
                    run_id,
                    status="failed",
                    stage="Failed",
                    error=str(exc)[:1000] or exc.__class__.__name__,
                )

    async def _valid_quantity(self, symbol: str, quantity: float, price: float) -> float:
        try:
            filters = await self.market.symbol_filters(symbol)
        except BinanceAPIError:
            if self.settings.mode != "paper":
                raise
            # Offline paper preview only. Conservative decimal steps mirror the
            # typical lot precision but are never used for Binance execution.
            filters = {
                "step_size": 0.000001 if price > 1000 else 0.0001,
                "min_qty": 0,
                "max_qty": 1e30,
                "min_notional": 5,
            }
        step = Decimal(str(filters["step_size"]))
        raw = Decimal(str(quantity))
        rounded = (raw / step).to_integral_value(rounding=ROUND_DOWN) * step
        result = float(rounded)
        if result < filters["min_qty"] or result > filters["max_qty"]:
            return 0
        if result * price < filters["min_notional"]:
            return 0
        return result

    def start_scheduler(self) -> None:
        if self.settings.auto_trading_enabled and self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._scheduler())

    async def _scheduler(self) -> None:
        delay = self.settings.interval_minutes * 60
        while True:
            try:
                await asyncio.sleep(delay)
                for symbol in self.settings.symbols:
                    self.submit(
                        symbol,
                        execute=self.settings.auto_execute,
                        internal=True,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled agent cycle failed to submit")

    async def shutdown(self) -> None:
        if self._scheduler_task:
            self._scheduler_task.cancel()
        for task in tuple(self._tasks):
            task.cancel()
        pending = [task for task in [self._scheduler_task, *self._tasks] if task]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
