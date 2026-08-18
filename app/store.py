"""JSON persistence for analysis runs."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.config import DATA_DIR


class RunStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "runs.json")
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows[-200:], indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, run: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._load()
            rows.append(run)
            self._save(rows)
            return run

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._load()
        return list(reversed(rows[-limit:]))

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._load()
        for row in reversed(rows):
            if row.get("id") == run_id:
                return row
        return None
