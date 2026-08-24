"""Rich cockpit. Termux uses a one-screen redraw (no Live flood)."""

from __future__ import annotations

import io
import os
import sys
from typing import Any

from app.config import get_settings

HELP = "[q]uit [p]ause [r]esume [s]trategy [m]arket [o]pen [t]rades [l]ogs [h]elp [e]mergency"


def _is_termux() -> bool:
    return bool(os.getenv("TERMUX_VERSION")) or os.path.isdir("/data/data/com.termux/files")


def _clear() -> str:
    return "\033[H\033[J" if sys.stdout.isatty() else ""


def _dot(ok: str) -> str:
    state = (ok or "").upper()
    if state in {"ONLINE", "OK", "READY", "LIVE", "CONNECTED"}:
        label = "ONLINE" if state == "OK" else state
        return f"● {label}"
    if state in {"DEGRADED"}:
        return "● DEGRADED"
    if state in {"DEMO"}:
        return "● DEMO"
    if state in {"PAUSED"}:
        return "● PAUSED"
    return "● OFFLINE"


def _money(value: Any, signed: bool = False) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    if signed:
        return f"${n:+,.2f}"
    return f"${n:,.2f}"


def _pct(value: Any) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    return f"{n:+.2f}%"


class CockpitUI:
    def __init__(self) -> None:
        self.rich = None
        self.console = None
        self.live = None
        self._use_live = False
        try:
            from rich.console import Console

            self.console = Console(force_terminal=True, width=min(100, os.get_terminal_size().columns if sys.stdout.isatty() else 88))
            self.rich = True
            self._use_live = sys.stdout.isatty() and not _is_termux()
        except Exception:
            self.rich = None
            self.console = None

    def render(self, view: dict[str, Any]) -> str:
        if self.console is not None:
            try:
                from rich.console import Console

                buf = Console(
                    record=True,
                    file=io.StringIO(),
                    width=getattr(self.console, "width", 88),
                    color_system=None,
                )
                buf.print(self._rich_renderable(view))
                return buf.export_text(styles=False)
            except Exception:
                pass
        return self._plain(view)

    def draw(self, view: dict[str, Any]) -> None:
        if self._use_live and self.console is not None:
            try:
                from rich.live import Live

                renderable = self._rich_renderable(view)
                if self.live is None:
                    self.live = Live(renderable, console=self.console, refresh_per_second=4, screen=False)
                    self.live.start()
                else:
                    self.live.update(renderable)
                return
            except Exception:
                self._use_live = False
                if self.live is not None:
                    try:
                        self.live.stop()
                    except Exception:
                        pass
                    self.live = None
        text = self.render(view)
        sys.stdout.write(_clear() + text + "\n")
        sys.stdout.flush()

    def stop(self) -> None:
        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                pass
            self.live = None

    def _rich_renderable(self, view: dict[str, Any]):
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        from rich.console import Group

        settings = get_settings()
        mode = settings.display_mode
        acct = view.get("account") or {}
        dec = view.get("decision") or {}
        health = view.get("health") or {}
        stages = view.get("stages") or {}
        watch = view.get("watch") or []
        pos = view.get("positions") or []
        page = (view.get("page") or "main").lower()
        paused = bool(view.get("paused"))
        emergency = bool(view.get("emergency"))
        status = "EMERGENCY STOP" if emergency else ("PAUSED" if paused else "ONLINE")

        head = Table.grid(expand=True)
        head.add_column()
        title = Text("HILA AI TRADING TERMINAL", style="bold cyan")
        head.add_row(title)
        head.add_row(Text("TradingAgents Brain", style="bold"))
        if emergency:
            head.add_row(Text("EMERGENCY STOP — explicit resume required", style="bold red"))
        elif paused:
            head.add_row(Text("ANALYSIS: ON    EXECUTION: PAUSED", style="bold yellow"))

        meta = Table.grid(padding=(0, 2))
        meta.add_column(style="dim")
        meta.add_column()
        meta.add_row("STATUS", status)
        meta.add_row("MODE", mode)
        meta.add_row("EXCHANGE", "CONNECTED" if health.get("Exchange") in {"ONLINE", "LIVE", "OK"} else str(health.get("Exchange") or "DISCONNECTED"))
        meta.add_row("BRAIN", "TradingAgents")
        meta.add_row("CYCLE", f"#{view.get('cycle', 0)}")
        meta.add_row("UPTIME", str(view.get("uptime") or "00:00:00"))
        auth = view.get("auth_line") or ""
        if auth:
            meta.add_row("AUTH", auth)

        acct_tbl = Table(title="ACCOUNT", show_header=False, box=None, expand=True)
        acct_tbl.add_column()
        acct_tbl.add_column(justify="right")
        acct_tbl.add_row("Wallet Balance", _money(acct.get("wallet_balance", acct.get("equity"))))
        acct_tbl.add_row("Available Balance", _money(acct.get("available", acct.get("cash"))))
        acct_tbl.add_row("Equity", _money(acct.get("equity")))
        acct_tbl.add_row("Used Margin", _money(acct.get("used_margin")))
        acct_tbl.add_row("Free Margin", _money(acct.get("free_margin", acct.get("cash"))))
        acct_tbl.add_row("Unrealized P&L", _money(acct.get("unrealized_pnl"), signed=True))
        acct_tbl.add_row("Realized P&L", _money(acct.get("realized_pnl"), signed=True))
        acct_tbl.add_row("Daily P&L", _pct(acct.get("day_pnl_pct")))
        acct_tbl.add_row("Total P&L", _pct(acct.get("total_pnl_pct", acct.get("pnl_pct"))))

        mkt = Table(title="MARKET", box=None, expand=True)
        mkt.add_column("Symbol")
        mkt.add_column("Price", justify="right")
        mkt.add_column("Signal")
        mkt.add_column("Conf", justify="right")
        mkt.add_column("Trend")
        for row in watch:
            mkt.add_row(
                str(row.get("symbol") or ""),
                f"{float(row.get('price') or 0):,.4f}",
                str(row.get("action") or "—"),
                f"{int(float(row.get('confidence') or 0) * 100)}%",
                str(row.get("trend") or ""),
            )
        if not watch:
            mkt.add_row("—", "loading", "—", "—", "—")

        firm = Table(title="TRADINGAGENTS", show_header=False, box=None, expand=True)
        firm.add_column()
        firm.add_column()
        labels = [
            ("market", "Technical Analyst"),
            ("sentiment", "Sentiment Analyst"),
            ("news", "News Analyst"),
            ("bull", "Bull Researcher"),
            ("bear", "Bear Researcher"),
            ("trader", "Trader"),
            ("risk", "Risk Manager"),
            ("portfolio", "Portfolio Manager"),
        ]
        for key, label in labels:
            st = (stages.get(key) or "PENDING").upper()
            mark = "✓" if st in {"COMPLETE", "SKIPPED", "EMPTY"} else ("✗" if st == "FAILED" else "…")
            firm.add_row(label, f"{mark} {st}")

        dec_tbl = Table(title="CURRENT DECISION", show_header=False, box=None, expand=True)
        dec_tbl.add_column()
        dec_tbl.add_column()
        status_d = str(dec.get("status") or dec.get("action") or "HOLD")
        if status_d == "ANALYSIS_FAILED":
            dec_tbl.add_row("Status", "ANALYSIS FAILED")
            dec_tbl.add_row("Reason", str(dec.get("error") or dec.get("reason") or dec.get("thesis") or "")[:160])
        else:
            dec_tbl.add_row("Symbol", str(dec.get("symbol") or "—"))
            dec_tbl.add_row("Action", str(dec.get("action") or "HOLD"))
            dec_tbl.add_row("Confidence", f"{int(float(dec.get('confidence') or 0) * 100)}%")
            dec_tbl.add_row("Entry", _money(dec.get("entry")))
            dec_tbl.add_row("Stop", _money(dec.get("stop_loss")))
            tps = dec.get("take_profit") or []
            dec_tbl.add_row("Target", _money(tps[0] if tps else 0))
            dec_tbl.add_row("Position", f"{float(dec.get('position_size') or 0):.1%}")
            rr = dec.get("risk_reward")
            dec_tbl.add_row("Risk/Reward", f"1:{rr}" if rr else "—")
            dec_tbl.add_row("Thesis", str(dec.get("thesis") or "waiting for firm cycle")[:200])

        pos_tbl = Table(title="POSITIONS", box=None, expand=True)
        pos_tbl.add_column("Symbol")
        pos_tbl.add_column("Entry", justify="right")
        pos_tbl.add_column("Current", justify="right")
        pos_tbl.add_column("Qty", justify="right")
        pos_tbl.add_column("P&L", justify="right")
        pos_tbl.add_column("Stop", justify="right")
        pos_tbl.add_column("Target", justify="right")
        brackets = view.get("brackets") or {}
        if pos:
            for p in pos:
                br = brackets.get(p.get("symbol"), {})
                pos_tbl.add_row(
                    str(p.get("symbol") or ""),
                    _money(p.get("avg_price")),
                    _money(p.get("mark")),
                    f"{float(p.get('qty') or 0):.6g}",
                    _money(p.get("unrealized_pnl"), signed=True),
                    _money(br.get("stop") or 0),
                    _money(br.get("take") or 0),
                )
        else:
            pos_tbl.add_row("flat", "—", "—", "—", "—", "—", "—")

        sys_tbl = Table(title="SYSTEM HEALTH", show_header=False, box=None, expand=True)
        sys_tbl.add_column()
        sys_tbl.add_column()
        sys_tbl.add_row("Exchange API", _dot(str(health.get("Exchange") or health.get("Binance") or "")))
        sys_tbl.add_row("Market Data", _dot(str(health.get("Market") or health.get("Exchange") or health.get("Binance") or "")))
        sys_tbl.add_row("TradingAgents", _dot(str(health.get("TradingAgents") or "")))
        sys_tbl.add_row("News", _dot(str(health.get("News") or "")))
        sys_tbl.add_row("Sentiment", _dot(str(health.get("Sentiment") or "")))
        sys_tbl.add_row("Execution", _dot(str(health.get("Execution") or "READY")))
        keys = health.get("Keys")
        if keys:
            sys_tbl.add_row("API Keys", str(keys))

        extra = self._page_block(view, page)
        parts = [
            Panel(Group(head, meta), border_style="cyan"),
            acct_tbl,
            mkt,
            firm,
            dec_tbl,
            pos_tbl,
            sys_tbl,
        ]
        if extra:
            parts.append(extra)
        parts.append(Text(HELP, style="dim"))
        cycle_line = view.get("cycle_line")
        if cycle_line:
            parts.append(Text(str(cycle_line), style="dim"))
        return Group(*parts)

    def _page_block(self, view: dict[str, Any], page: str):
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text

        if page in {"", "main"}:
            return None
        if page == "help":
            return Panel(
                "q quit  p pause analysis-on/execution-off  r resume\n"
                "s last strategy  m market tape  o open positions  t trades\n"
                "l recent logs  e emergency stop (does not auto-resume)\n"
                "touch data/HALT also stops the loop.",
                title="HELP",
            )
        if page == "strategy":
            dec = view.get("decision") or {}
            body = (
                f"Brain: TradingAgents\n"
                f"Rating: {dec.get('rating')}\n"
                f"Bull: {str(dec.get('bull_case') or '')[:400]}\n"
                f"Bear: {str(dec.get('bear_case') or '')[:400]}\n"
                f"Risk: {str(dec.get('risk_assessment') or '')[:400]}"
            )
            return Panel(body, title="STRATEGY / REPORT")
        if page == "market":
            rows = view.get("watch") or []
            tbl = Table(title="MARKET DATA")
            tbl.add_column("Symbol")
            tbl.add_column("Price")
            tbl.add_column("Trend")
            tbl.add_column("Note")
            for row in rows:
                tbl.add_row(
                    str(row.get("symbol") or ""),
                    f"{float(row.get('price') or 0):,.4f}",
                    str(row.get("trend") or ""),
                    str(row.get("note") or "")[:40],
                )
            return tbl
        if page == "positions":
            pos = view.get("positions") or []
            if not pos:
                return Panel("No open positions.", title="OPEN POSITIONS")
            return Panel("\n".join(str(p) for p in pos)[:1200], title="OPEN POSITIONS")
        if page == "trades":
            trades = view.get("trades") or []
            if not trades:
                return Panel("No fills yet.", title="RECENT TRADES")
            lines = []
            for t in trades[-12:]:
                lines.append(
                    f"{t.get('id') or t.get('trade_id')} {t.get('symbol')} "
                    f"{t.get('side')} {t.get('qty')} @ {t.get('price')} {t.get('reason')}"
                )
            return Panel("\n".join(lines), title="RECENT TRADES")
        if page == "logs":
            logs = view.get("logs") or []
            return Panel("\n".join(str(x) for x in logs[-16:]) or "no log lines", title="LOGS")
        return Text("")

    def _plain(self, view: dict[str, Any]) -> str:
        settings = get_settings()
        mode = settings.display_mode
        acct = view.get("account") or {}
        dec = view.get("decision") or {}
        health = view.get("health") or {}
        stages = view.get("stages") or {}
        watch = view.get("watch") or []
        pos = view.get("positions") or []
        paused = bool(view.get("paused"))
        emergency = bool(view.get("emergency"))
        lines = [
            "============================================================",
            "HILA AI TRADING TERMINAL",
            "TradingAgents Brain",
            "",
            f"STATUS       {'● EMERGENCY STOP' if emergency else ('● PAUSED' if paused else '● ONLINE')}",
            f"MODE         {mode}",
            f"EXCHANGE     {health.get('Exchange') or health.get('Binance') or '—'}",
            "BRAIN        TradingAgents",
            f"CYCLE        #{view.get('cycle', 0)}",
            f"UPTIME       {view.get('uptime') or '00:00:00'}",
            "",
            "ACCOUNT",
            f"Wallet Balance      {_money(acct.get('wallet_balance', acct.get('equity')))}",
            f"Available           {_money(acct.get('available', acct.get('cash')))}",
            f"Equity              {_money(acct.get('equity'))}",
            f"Used Margin         {_money(acct.get('used_margin'))}",
            f"Free Margin         {_money(acct.get('free_margin', acct.get('cash')))}",
            f"Unrealized P&L      {_money(acct.get('unrealized_pnl'), signed=True)}",
            f"Realized P&L        {_money(acct.get('realized_pnl'), signed=True)}",
            f"Daily P&L           {_pct(acct.get('day_pnl_pct'))}",
            f"Total P&L           {_pct(acct.get('total_pnl_pct', acct.get('pnl_pct')))}",
            "",
            "MARKET",
        ]
        if watch:
            for row in watch:
                lines.append(
                    f"{str(row.get('symbol') or ''):<10} "
                    f"{float(row.get('price') or 0):>12.4f}    "
                    f"{str(row.get('action') or '—'):<6} "
                    f"{int(float(row.get('confidence') or 0) * 100)}%"
                )
        else:
            lines.append("watch: loading")
        lines += ["", "TRADINGAGENTS"]
        order = [
            ("market", "Technical Analyst"),
            ("sentiment", "Sentiment Analyst"),
            ("news", "News Analyst"),
            ("bull", "Bull Researcher"),
            ("bear", "Bear Researcher"),
            ("trader", "Trader"),
            ("risk", "Risk Manager"),
            ("portfolio", "Portfolio Manager"),
        ]
        for key, label in order:
            st = (stages.get(key) or "PENDING").upper()
            mark = "✓" if st in {"COMPLETE", "SKIPPED", "EMPTY"} else ("✗" if st == "FAILED" else "…")
            lines.append(f"{label:<24} {mark}")
        lines += ["", "CURRENT DECISION"]
        if (dec.get("status") or "") == "ANALYSIS_FAILED":
            lines.append(f"ANALYSIS FAILED")
            lines.append(f"Reason: {dec.get('error') or dec.get('reason') or dec.get('thesis')}")
        else:
            tps = dec.get("take_profit") or []
            lines.append(f"Symbol: {dec.get('symbol') or '—'}")
            lines.append(f"Action: {dec.get('action') or 'HOLD'}")
            lines.append(f"Confidence: {int(float(dec.get('confidence') or 0) * 100)}%")
            lines.append(f"Entry: {_money(dec.get('entry'))}")
            lines.append(f"Stop: {_money(dec.get('stop_loss'))}")
            lines.append(f"Target: {_money(tps[0] if tps else 0)}")
            lines.append(f"Position: {float(dec.get('position_size') or 0):.1%}")
            rr = dec.get("risk_reward")
            lines.append(f"Risk/Reward: {('1:' + str(rr)) if rr else '—'}")
        lines += ["", "POSITIONS"]
        if pos:
            for p in pos:
                lines.append(str(p.get("symbol") or ""))
                lines.append(f"Entry:       {_money(p.get('avg_price'))}")
                lines.append(f"Current:     {_money(p.get('mark'))}")
                lines.append(f"Quantity:    {float(p.get('qty') or 0):.6g}")
                lines.append(f"P&L:         {_money(p.get('unrealized_pnl'), signed=True)}")
        else:
            lines.append("flat")
        lines += [
            "",
            "SYSTEM HEALTH",
            f"Exchange API        {_dot(str(health.get('Exchange') or health.get('Binance') or ''))}",
            f"Market Data         {_dot(str(health.get('Market') or health.get('Exchange') or health.get('Binance') or ''))}",
            f"TradingAgents       {_dot(str(health.get('TradingAgents') or ''))}",
            f"News                {_dot(str(health.get('News') or ''))}",
            f"Execution           {_dot(str(health.get('Execution') or 'READY'))}",
            "============================================================",
            HELP,
        ]
        if view.get("cycle_line"):
            lines.append(str(view["cycle_line"]))
        return "\n".join(lines)
