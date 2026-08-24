"""JSON cockpit state — decisions, trades, halt flags, brackets."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def trade_id(symbol: str, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"TRADE-{stamp}-{symbol}"


@dataclass
class CockpitState:
    day: str = field(default_factory=utc_day)
    start_equity: float | None = None
    last_trade: dict[str, str] = field(default_factory=dict)
    halted: bool = False
    paused: bool = False
    emergency: bool = False
    goal_hit: bool = False
    decisions: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    brackets: dict[str, Any] = field(default_factory=dict)
    cycle: int = 0
    synced: bool = True
    page: str = "main"
    cycle_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "start_equity": self.start_equity,
            "last_trade": self.last_trade,
            "halted": self.halted,
            "paused": self.paused,
            "emergency": self.emergency,
            "goal_hit": self.goal_hit,
            "decisions": self.decisions[-80:],
            "trades": self.trades[-80:],
            "brackets": self.brackets,
            "cycle": self.cycle,
            "synced": self.synced,
            "page": self.page,
            "cycle_log": self.cycle_log[-40:],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CockpitState:
        return cls(
            day=str(data.get("day") or utc_day()),
            start_equity=data.get("start_equity"),
            last_trade=dict(data.get("last_trade") or {}),
            halted=bool(data.get("halted")),
            paused=bool(data.get("paused")),
            emergency=bool(data.get("emergency")),
            goal_hit=bool(data.get("goal_hit")),
            decisions=list(data.get("decisions") or []),
            trades=list(data.get("trades") or []),
            brackets=dict(data.get("brackets") or {}),
            cycle=int(data.get("cycle") or 0),
            synced=bool(data.get("synced", True)),
            page=str(data.get("page") or "main"),
            cycle_log=list(data.get("cycle_log") or []),
        )


def _path() -> Path:
    return DATA_DIR / "cockpit.json"


def load_state() -> CockpitState:
    path = _path()
    if not path.exists():
        return CockpitState()
    try:
        return CockpitState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return CockpitState()


def save_state(state: CockpitState) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
