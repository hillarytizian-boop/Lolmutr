"""In-process paper broker filled at the latest Binance last price."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, get_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperBroker:
    def __init__(self, path: Path | None = None, starting_cash: float | None = None) -> None:
        settings = get_settings()
        self.path = path or (DATA_DIR / "paper.json")
        self.starting_cash = (
            starting_cash if starting_cash is not None else settings.paper_starting_cash
        )
        self._lock = threading.Lock()
        self.state = self._load()

    def _empty(self) -> dict[str, Any]:
        return {
            "cash": float(self.starting_cash),
            "starting_cash": float(self.starting_cash),
            "positions": {},
            "orders": [],
            "equity_curve": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self, marks: dict[str, float] | None = None) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked(marks or {})

    def _snapshot_unlocked(self, marks: dict[str, float]) -> dict[str, Any]:
        positions = []
        unrealized = 0.0
        for symbol, pos in self.state["positions"].items():
            qty = float(pos["qty"])
            avg = float(pos["avg_price"])
            mark = float(marks.get(symbol, avg))
            upnl = (mark - avg) * qty
            unrealized += upnl
            positions.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "avg_price": avg,
                    "mark": mark,
                    "notional": mark * qty,
                    "unrealized_pnl": upnl,
                    "realized_pnl": float(pos.get("realized_pnl") or 0),
                }
            )
        cash = float(self.state["cash"])
        equity = cash + sum(p["notional"] for p in positions)
        start = float(self.state.get("starting_cash") or self.starting_cash)
        return {
            "mode": "paper",
            "cash": cash,
            "equity": equity,
            "unrealized_pnl": unrealized,
            "realized_pnl": sum(float(o.get("realized_pnl") or 0) for o in self.state["orders"]),
            "pnl": equity - start,
            "pnl_pct": ((equity - start) / start * 100.0) if start else 0.0,
            "positions": positions,
            "orders": list(reversed(self.state["orders"][-50:])),
        }

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self.state = self._empty()
            self._save()
            return self._snapshot_unlocked({})

    def market_order(
        self,
        symbol: str,
        side: str,
        quantity: float | None = None,
        notional: float | None = None,
        price: float = 0.0,
        reason: str = "",
        fee_bps: float = 10.0,
    ) -> dict[str, Any]:
        side_u = side.upper()
        if side_u not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if price <= 0:
            raise ValueError("price must be positive")
        if quantity is None:
            if notional is None or notional <= 0:
                raise ValueError("quantity or notional is required")
            quantity = notional / price
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        fee = price * quantity * (fee_bps / 10_000.0)
        with self._lock:
            cash = float(self.state["cash"])
            pos = self.state["positions"].get(
                symbol, {"qty": 0.0, "avg_price": 0.0, "realized_pnl": 0.0}
            )
            qty = float(pos["qty"])
            avg = float(pos["avg_price"])
            realized = 0.0

            if side_u == "BUY":
                cost = price * quantity + fee
                if cost > cash + 1e-9:
                    raise ValueError("insufficient paper cash")
                new_qty = qty + quantity
                pos["avg_price"] = ((avg * qty) + price * quantity) / new_qty if new_qty else 0.0
                pos["qty"] = new_qty
                self.state["cash"] = cash - cost
            else:
                sell_qty = min(qty, quantity)
                if sell_qty <= 0:
                    raise ValueError("no position to sell")
                proceeds = price * sell_qty - fee
                realized = (price - avg) * sell_qty - fee
                pos["qty"] = qty - sell_qty
                pos["realized_pnl"] = float(pos.get("realized_pnl") or 0) + realized
                if pos["qty"] <= 1e-12:
                    pos["qty"] = 0.0
                    pos["avg_price"] = 0.0
                self.state["cash"] = cash + proceeds
                quantity = sell_qty

            if pos["qty"] > 0:
                self.state["positions"][symbol] = pos
            elif symbol in self.state["positions"]:
                del self.state["positions"][symbol]

            order = {
                "id": uuid.uuid4().hex[:12],
                "ts": _now(),
                "symbol": symbol,
                "side": side_u,
                "qty": quantity,
                "price": price,
                "fee": fee,
                "notional": price * quantity,
                "reason": reason,
                "realized_pnl": realized,
                "status": "filled",
                "venue": "paper",
            }
            self.state["orders"].append(order)
            snap = self._snapshot_unlocked({symbol: price})
            self.state["equity_curve"].append(
                {"ts": order["ts"], "equity": snap["equity"], "price": price, "symbol": symbol}
            )
            self.state["equity_curve"] = self.state["equity_curve"][-500:]
            self._save()
            return order
