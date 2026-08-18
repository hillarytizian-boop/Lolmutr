"""Command entry: setup, trade, serve."""

from __future__ import annotations

import sys


HELP = """\
Lolmutr — Binance desk on TradingAgents

  python -m app setup          enter LLM + Binance keys, then auto-trade
  python -m app setup --start  same, skip the final confirm
  python -m app trade          start the autotrader (uses .env)
  python -m app once           one cycle and exit
  python -m app serve          web desk (default)

Termux:
  bash scripts/termux-setup.sh

Stop the loop with Ctrl+C or:  touch data/HALT
"""


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = (args[0] if args else "serve").lower()
    rest = args[1:]

    if cmd in {"-h", "--help", "help"}:
        print(HELP)
        return
    if cmd in {"setup", "init"}:
        from app.setup_wizard import run_setup

        run_setup(start="--start" in rest or "-y" in rest)
        return
    if cmd in {"trade", "auto", "trader"}:
        from app.autotrader import run_autotrader

        run_autotrader(once=False)
        return
    if cmd in {"once"}:
        from app.autotrader import run_autotrader

        run_autotrader(once=True)
        return
    if cmd in {"serve", "web", "desk"}:
        try:
            from app.main import run
        except ImportError:
            print(
                "Web desk needs FastAPI. On a computer:\n"
                "  pip install -r requirements-web.txt\n"
                "On Termux stay with:  python -m app trade"
            )
            sys.exit(1)
        run()
        return
    print(HELP)
    sys.exit(1)
