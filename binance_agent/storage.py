from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import OrderRecord, RunRecord


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path, quote_asset: str, starting_balance: float) -> None:
        self.path = path
        self.quote_asset = quote_asset
        self.starting_balance = starting_balance
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self._initialize_paper_account()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS balances (
                    asset TEXT PRIMARY KEY,
                    free REAL NOT NULL DEFAULT 0,
                    locked REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    notional REAL NOT NULL,
                    fee REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    external_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    execute_requested INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
                """
            )
            self._connection.execute(
                """
                UPDATE runs
                SET status = 'failed', stage = 'Interrupted',
                    error = 'The service restarted before this run completed', updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (utc_now(),),
            )

    def _initialize_paper_account(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO balances(asset, free, locked, updated_at)
                VALUES (?, ?, 0, ?)
                """,
                (self.quote_asset, self.starting_balance, utc_now()),
            )

    def reset_paper_account(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM orders WHERE mode = 'paper'")
            self._connection.execute("DELETE FROM balances")
            self._connection.execute(
                "INSERT INTO balances(asset, free, locked, updated_at) VALUES (?, ?, 0, ?)",
                (self.quote_asset, self.starting_balance, utc_now()),
            )

    def balances(self) -> dict[str, dict[str, float]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT asset, free, locked FROM balances ORDER BY asset"
            ).fetchall()
        return {
            row["asset"]: {"free": float(row["free"]), "locked": float(row["locked"])}
            for row in rows
        }

    def create_run(self, symbol: str, execute_requested: bool) -> RunRecord:
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO runs(id, symbol, status, stage, execute_requested, created_at, updated_at)
                VALUES (?, ?, 'queued', 'Queued', ?, ?, ?)
                """,
                (run_id, symbol, int(execute_requested), now, now),
            )
        return self.get_run(run_id)

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> RunRecord:
        fields = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        for key, value in (("status", status), ("stage", stage), ("error", error)):
            if value is not None:
                fields.append(f"{key} = ?")
                values.append(value)
        if result is not None:
            fields.append("result_json = ?")
            values.append(json.dumps(result, separators=(",", ":"), default=str))
        values.append(run_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE runs SET {', '.join(fields)} WHERE id = ?", values
            )
            if not cursor.rowcount:
                raise KeyError(run_id)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RunRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._run_from_row(row)

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            symbol=row["symbol"],
            status=row["status"],
            stage=row["stage"],
            execute_requested=bool(row["execute_requested"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def execute_paper_order(
        self,
        *,
        symbol: str,
        base_asset: str,
        side: str,
        quantity: float,
        price: float,
        fee_rate: float = 0.001,
    ) -> OrderRecord:
        order_id = uuid.uuid4().hex
        notional = quantity * price
        fee = notional * fee_rate
        now = utc_now()
        with self._lock, self._connection:
            balances = self.balances()
            quote_free = balances.get(self.quote_asset, {}).get("free", 0)
            base_free = balances.get(base_asset, {}).get("free", 0)
            if side == "BUY":
                total = notional + fee
                if total > quote_free + 1e-9:
                    raise ValueError("Insufficient paper quote balance")
                quote_free -= total
                base_free += quantity
            elif side == "SELL":
                if quantity > base_free + 1e-12:
                    raise ValueError("Insufficient paper asset balance")
                base_free -= quantity
                quote_free += notional - fee
            else:
                raise ValueError(f"Unsupported side: {side}")

            for asset, amount in ((self.quote_asset, quote_free), (base_asset, base_free)):
                self._connection.execute(
                    """
                    INSERT INTO balances(asset, free, locked, updated_at)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(asset) DO UPDATE SET free = excluded.free, updated_at = excluded.updated_at
                    """,
                    (asset, max(amount, 0), now),
                )
            self._connection.execute(
                """
                INSERT INTO orders(
                    id, symbol, side, quantity, price, notional, fee, status, mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'FILLED', 'paper', ?)
                """,
                (order_id, symbol, side, quantity, price, notional, fee, now),
            )
        return self.get_order(order_id)

    def record_external_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        status: str,
        mode: str,
        external_id: str,
    ) -> OrderRecord:
        order_id = uuid.uuid4().hex
        now = utc_now()
        notional = quantity * price
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO orders(
                    id, symbol, side, quantity, price, notional, fee, status,
                    mode, external_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    symbol,
                    side,
                    quantity,
                    price,
                    notional,
                    status,
                    mode,
                    external_id,
                    now,
                ),
            )
        return self.get_order(order_id)

    def get_order(self, order_id: str) -> OrderRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        if row is None:
            raise KeyError(order_id)
        return OrderRecord(**dict(row))

    def list_orders(self, limit: int = 20) -> list[OrderRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [OrderRecord(**dict(row)) for row in rows]
