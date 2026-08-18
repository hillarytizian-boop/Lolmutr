from __future__ import annotations

from typing import Protocol

from .market import MarketDataClient
from .models import OrderRecord
from .storage import Store


class Broker(Protocol):
    mode: str

    async def balances(self) -> dict[str, dict[str, float]]: ...

    async def market_order(
        self, *, symbol: str, side: str, quantity: float, reference_price: float
    ) -> OrderRecord: ...


class PaperBroker:
    mode = "paper"

    def __init__(self, store: Store, quote_asset: str) -> None:
        self.store = store
        self.quote_asset = quote_asset

    async def balances(self) -> dict[str, dict[str, float]]:
        return self.store.balances()

    async def market_order(
        self, *, symbol: str, side: str, quantity: float, reference_price: float
    ) -> OrderRecord:
        base_asset = symbol.removesuffix(self.quote_asset)
        return self.store.execute_paper_order(
            symbol=symbol,
            base_asset=base_asset,
            side=side,
            quantity=quantity,
            price=reference_price,
        )


class BinanceBroker:
    def __init__(self, client: MarketDataClient, store: Store, mode: str) -> None:
        self.client = client
        self.store = store
        self.mode = mode

    async def balances(self) -> dict[str, dict[str, float]]:
        account = await self.client.signed_request("GET", "/api/v3/account")
        return {
            item["asset"]: {
                "free": float(item["free"]),
                "locked": float(item["locked"]),
            }
            for item in account.get("balances", [])
            if float(item["free"]) or float(item["locked"])
        }

    async def market_order(
        self, *, symbol: str, side: str, quantity: float, reference_price: float
    ) -> OrderRecord:
        payload = await self.client.signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": f"{quantity:.12f}".rstrip("0").rstrip("."),
                "newOrderRespType": "FULL",
            },
        )
        executed = float(payload.get("executedQty", quantity))
        fills = payload.get("fills", [])
        quote_quantity = float(payload.get("cummulativeQuoteQty", 0))
        average_price = quote_quantity / executed if executed and quote_quantity else reference_price
        if fills and not quote_quantity:
            total = sum(float(fill["price"]) * float(fill["qty"]) for fill in fills)
            average_price = total / executed if executed else reference_price
        return self.store.record_external_order(
            symbol=symbol,
            side=side,
            quantity=executed,
            price=average_price,
            status=payload.get("status", "UNKNOWN"),
            mode=self.mode,
            external_id=str(payload.get("orderId", "")),
        )
