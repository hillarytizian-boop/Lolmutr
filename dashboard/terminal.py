"""One-screen Termux dashboard. No Rich Live — that reprints and floods the phone."""

from __future__ import annotations

import sys
from typing import Any

from app.config import get_settings

HELP = "[q] quit  [p] pause  [r] resume"


def _clear() -> str:
    return "\033[H\033[J" if sys.stdout.isatty() else ""


class CockpitUI:
    def __init__(self) -> None:
        self.rich = None
        self.console = None
        self.live = None

    def render(self, view: dict[str, Any]) -> str:
        return self._plain(view)

    def draw(self, view: dict[str, Any]) -> None:
        sys.stdout.write(_clear() + self._plain(view) + "\n")
        sys.stdout.flush()

    def _plain(self, view: dict[str, Any]) -> str:
        settings = get_settings()
        live = settings.trading_mode == "live" and settings.live_unlocked
        mode = "LIVE" if live else "DEMO"
        acct = view.get("account") or {}
        dec = view.get("decision") or {}
        health = view.get("health") or {}
        stages = view.get("stages") or {}
        watch = view.get("watch") or []
        pos = view.get("positions") or []

        lines = [
            "HILA  TradingAgents  " + mode + f"  #{view.get('cycle', 0)}  {view.get('clock', '')}",
            "paper wallet" if not live else "LIVE real funds",
            f"eq ${float(acct.get('equity') or 0):.2f}  cash ${float(acct.get('cash') or 0):.2f}  "
            f"day {float(acct.get('day_pnl_pct') or 0):+.2f}%  tot {float(acct.get('pnl_pct') or 0):+.2f}%",
            "",
        ]
        if watch:
            bits = []
            for row in watch:
                bits.append(
                    f"{str(row.get('symbol','')).replace('USDT','')}"
                    f" {float(row.get('price') or 0):.5g}"
                    f" {(row.get('trend') or '')[:3]}"
                    f" {(row.get('action') or '-')[:4]}"
                )
            lines.append("  ".join(bits))
        else:
            lines.append("watch: loading")

        order = [
            ("market", "T"),
            ("sentiment", "S"),
            ("news", "N"),
            ("bull", "Bu"),
            ("bear", "Be"),
            ("trader", "Tr"),
            ("risk", "R"),
            ("portfolio", "PM"),
        ]
        firm = []
        for key, short in order:
            st = stages.get(key, "-")
            mark = "+" if st in {"COMPLETE", "SKIPPED", "EMPTY"} else st[:1]
            firm.append(f"{short}{mark}")
        lines.append("firm " + " ".join(firm))
        lines.append("")
        thesis = (dec.get("thesis") or "waiting for firm cycle")[:160].replace("\n", " ")
        lines.append(
            f"{dec.get('symbol') or '—'}  {dec.get('action') or 'HOLD'}  "
            f"{dec.get('rating') or 'Hold'}  "
            f"conf {int((dec.get('confidence') or 0) * 100)}%"
        )
        lines.append(thesis)
        if pos:
            lines.append(
                "pos "
                + "  ".join(
                    f"{p.get('symbol','').replace('USDT','')} {float(p.get('unrealized_pnl') or 0):+.2f}"
                    for p in pos
                )
            )
        else:
            lines.append("pos flat")
        h = "  ".join(f"{k.split()[0]}:{v}" for k, v in health.items())
        lines.append(h)
        lines.append(HELP)
        return "\n".join(lines)
