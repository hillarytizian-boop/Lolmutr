"""Termux-first cockpit: stacked panels, no 3-column crush, no HTML entities."""

from __future__ import annotations

from typing import Any

from app.config import get_settings

HELP = "[q] quit  [p] pause  [r] resume  [t] report"


def _try_rich():
    try:
        from rich import box
        from rich.console import Console, Group
        from rich.live import Live
        from rich.panel import Panel
        from rich.table import Table

        return {
            "box": box,
            "Console": Console,
            "Group": Group,
            "Live": Live,
            "Panel": Panel,
            "Table": Table,
        }
    except ImportError:
        return None


class CockpitUI:
    def __init__(self) -> None:
        self.rich = _try_rich()
        self.console = self.rich["Console"](width=min(72, 80)) if self.rich else None
        self.live = None

    def render(self, view: dict[str, Any]) -> Any:
        if not self.rich:
            return self._plain(view)
        R = self.rich
        settings = get_settings()
        live = settings.trading_mode == "live" and settings.live_unlocked
        mode = "LIVE" if live else "DEMO"
        acct = view.get("account") or {}
        dec = view.get("decision") or {}
        health = view.get("health") or {}

        head = R["Table"].grid(expand=True)
        head.add_column()
        head.add_row("[bold]HILA  TradingAgents[/]")
        head.add_row(
            f"{mode}  cycle #{view.get('cycle', 0)}  {view.get('clock', '')}"
        )
        head.add_row("DEMO — paper wallet" if not live else "LIVE — real funds")

        acc = R["Table"](box=R["box"].SIMPLE, expand=True, show_header=False)
        acc.add_column()
        acc.add_column(justify="right")
        acc.add_row("Equity", f"${float(acct.get('equity') or 0):.2f}")
        acc.add_row("Cash", f"${float(acct.get('cash') or 0):.2f}")
        acc.add_row("Day PnL", f"{float(acct.get('day_pnl_pct') or 0):+.2f}%")
        acc.add_row("Total PnL", f"{float(acct.get('pnl_pct') or 0):+.2f}%")

        watch = R["Table"](box=R["box"].SIMPLE, expand=True)
        watch.add_column("Sym", style="bold")
        watch.add_column("Px", justify="right")
        watch.add_column("Trend")
        watch.add_column("Sig")
        for row in view.get("watch") or []:
            watch.add_row(
                str(row.get("symbol", "")).replace("USDT", ""),
                f"{row.get('price', 0):.4g}",
                str(row.get("trend", ""))[:3],
                str(row.get("action", "HOLD"))[:4],
            )

        stages = R["Table"](box=R["box"].SIMPLE, expand=True, show_header=False)
        stages.add_column()
        stages.add_column()
        labels = [
            ("market", "Tech"),
            ("sentiment", "Sent"),
            ("news", "News"),
            ("bull", "Bull"),
            ("bear", "Bear"),
            ("trader", "Trader"),
            ("risk", "Risk"),
            ("portfolio", "PM"),
        ]
        for key, label in labels:
            st = (view.get("stages") or {}).get(key, "IDLE")
            mark = "ok" if st in {"COMPLETE", "SKIPPED", "EMPTY"} else st[:4]
            stages.add_row(label, mark)

        thesis = (dec.get("thesis") or "Waiting for first firm cycle.")[:220]
        decision = (
            f"{dec.get('symbol', '—')}  {dec.get('action', 'HOLD')}  "
            f"{dec.get('rating', 'Hold')}\n"
            f"conf {int((dec.get('confidence') or 0) * 100)}%  "
            f"size {float(dec.get('position_size') or 0):.0%}\n"
            f"{thesis}"
        )

        pos = view.get("positions") or []
        pos_line = "flat"
        if pos:
            pos_line = "  ".join(
                f"{p.get('symbol','').replace('USDT','')} {p.get('unrealized_pnl',0):+.2f}"
                for p in pos
            )

        sys_line = "  ".join(f"{k.split()[0]}:{v}" for k, v in health.items())

        return R["Group"](
            R["Panel"](head, title="HILA"),
            R["Panel"](acc, title="ACCOUNT"),
            R["Panel"](watch, title="WATCH"),
            R["Panel"](stages, title="FIRM"),
            R["Panel"](decision, title="DECISION"),
            R["Panel"](pos_line, title="POSITIONS"),
            R["Panel"](sys_line + "\n" + HELP, title="HEALTH"),
        )

    def _plain(self, view: dict[str, Any]) -> str:
        dec = view.get("decision") or {}
        acct = view.get("account") or {}
        return (
            f"[{view.get('clock')}] #{view.get('cycle')} "
            f"equity=${float(acct.get('equity') or 0):.2f} "
            f"{dec.get('symbol', '')} {dec.get('action', 'HOLD')}"
        )
