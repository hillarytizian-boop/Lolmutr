"""Rich cockpit. TradingAgents is the brain; this is only the glass."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import get_settings


def _try_rich():
    try:
        from rich import box
        from rich.align import Align
        from rich.console import Console, Group
        from rich.layout import Layout
        from rich.live import Live
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        return {
            "box": box,
            "Align": Align,
            "Console": Console,
            "Group": Group,
            "Layout": Layout,
            "Live": Live,
            "Panel": Panel,
            "Table": Table,
            "Text": Text,
        }
    except ImportError:
        return None


HELP = """\
[q] quit   [p] pause   [r] resume   [t] last report
[o] positions   [l] history   [h] help
"""


class CockpitUI:
    def __init__(self) -> None:
        self.rich = _try_rich()
        self.console = self.rich["Console"]() if self.rich else None
        self.live = None

    def render(self, view: dict[str, Any]) -> Any:
        if not self.rich:
            return self._plain(view)
        R = self.rich
        settings = get_settings()
        live = settings.trading_mode == "live" and settings.live_unlocked
        mode = "LIVE" if live else "DEMO"
        mode_style = "bold white on red" if live else "bold black on yellow"
        banner = (
            "⚠ LIVE TRADING — real funds"
            if live
            else "⚠ DEMO MODE — no real funds used"
        )

        header = R["Table"].grid(expand=True)
        header.add_column(justify="left")
        header.add_column(justify="center")
        header.add_column(justify="right")
        header.add_row(
            f"[bold]HILA AI TRADING TERMINAL[/]\n[dim]TradingAgents Intelligence Engine[/]",
            f"[{mode_style}] {mode} [/{mode_style}]\n{banner}",
            f"cycle #{view.get('cycle', 0)}  {view.get('clock', '')}",
        )

        acct = view.get("account") or {}
        acc = R["Table"](box=R["box"].SIMPLE, expand=True)
        acc.add_column("ACCOUNT")
        acc.add_column(justify="right")
        acc.add_row("Balance", f"${acct.get('cash', 0):.2f}")
        acc.add_row("Equity", f"${acct.get('equity', 0):.2f}")
        acc.add_row("Available", f"${acct.get('cash', 0):.2f}")
        acc.add_row("Unrealized P&L", f"${acct.get('unrealized_pnl', 0):+.2f}")
        acc.add_row("Daily P&L", f"{acct.get('day_pnl_pct', 0):+.2f}%")
        acc.add_row("Total P&L", f"{acct.get('pnl_pct', 0):+.2f}%")
        acc.add_row("Source", "LIVE BALANCE" if live else "DEMO BALANCE")

        watch = R["Table"](box=R["box"].SIMPLE, expand=True)
        watch.add_column("Symbol")
        watch.add_column("Price", justify="right")
        watch.add_column("Trend")
        watch.add_column("Signal")
        watch.add_column("Conf")
        for row in view.get("watch") or []:
            watch.add_row(
                row.get("symbol", ""),
                f"${row.get('price', 0):,.4g}",
                row.get("trend", ""),
                row.get("action", "HOLD"),
                f"{int((row.get('confidence') or 0) * 100)}%",
            )

        stages = R["Table"](box=R["box"].SIMPLE, expand=True)
        stages.add_column("TRADINGAGENTS BRAIN")
        stages.add_column("Status")
        labels = {
            "market": "Technical Analyst",
            "sentiment": "Sentiment Analyst",
            "news": "News Analyst",
            "fundamentals": "Fundamentals",
            "bull": "Bull Researcher",
            "bear": "Bear Researcher",
            "trader": "Trader",
            "risk": "Risk Management",
            "portfolio": "Portfolio Manager",
        }
        for key, label in labels.items():
            st = (view.get("stages") or {}).get(key, "IDLE")
            mark = "✓" if st in {"COMPLETE", "SKIPPED", "EMPTY"} else "…"
            stages.add_row(label, f"{mark} {st}")

        dec = view.get("decision") or {}
        reason = (dec.get("thesis") or "Awaiting first TradingAgents cycle.")[:280]
        current = (
            f"[bold]{dec.get('symbol', '—')}[/]   Decision: [bold]{dec.get('action', 'HOLD')}[/]\n"
            f"Rating: {dec.get('rating', 'Hold')}   Confidence: "
            f"{int((dec.get('confidence') or 0) * 100)}%\n"
            f"Position: {float(dec.get('position_size') or 0):.0%}   "
            f"Brain: {dec.get('brain', 'TradingAgents')}\n"
            f"[dim]{reason}[/]"
        )

        pos_tbl = R["Table"](box=R["box"].SIMPLE, expand=True)
        pos_tbl.add_column("POSITIONS")
        pos_tbl.add_column("Qty", justify="right")
        pos_tbl.add_column("uPnL", justify="right")
        positions = view.get("positions") or []
        if not positions:
            pos_tbl.add_row("None", "", "")
        for p in positions:
            pos_tbl.add_row(p.get("symbol", ""), f"{p.get('qty', 0):.6g}", f"{p.get('unrealized_pnl', 0):+.2f}")

        health = R["Table"](box=R["box"].SIMPLE, expand=True)
        health.add_column("SYSTEM HEALTH")
        health.add_column("Status")
        for name, status in (view.get("health") or {}).items():
            health.add_row(name, status)

        layout = R["Layout"]()
        layout.split_column(
            R["Layout"](R["Panel"](header, style="white"), size=5),
            R["Layout"](name="mid"),
            R["Layout"](R["Panel"](current, title="CURRENT DECISION"), size=8),
            R["Layout"](name="low", size=8),
            R["Layout"](R["Panel"](HELP, style="dim"), size=3),
        )
        layout["mid"].split_row(
            R["Layout"](R["Panel"](acc)),
            R["Layout"](R["Panel"](watch, title="MARKET WATCH")),
            R["Layout"](R["Panel"](stages)),
        )
        layout["low"].split_row(
            R["Layout"](R["Panel"](pos_tbl)),
            R["Layout"](R["Panel"](health)),
        )
        return layout

    def _plain(self, view: dict[str, Any]) -> str:
        dec = view.get("decision") or {}
        acct = view.get("account") or {}
        return (
            f"[{view.get('clock')}] cycle={view.get('cycle')} "
            f"equity=${acct.get('equity', 0):.2f} "
            f"{dec.get('symbol', '')} {dec.get('action', 'HOLD')} "
            f"brain={dec.get('brain', 'TradingAgents')}"
        )
