"""Command entry: setup, trade, serve."""

from __future__ import annotations

import sys


HELP = """\
Lolmutr — Binance desk on TradingAgents

  python -m app setup          enter LLM + Binance keys, then auto-trade
  python -m app setup --start  same, skip the final confirm
  python -m app trade          start the autotrader (uses .env)
  python -m app once           one cycle and exit
  python -m app test           DEMO end-to-end self-check
  python -m app serve          web desk (default)

Termux:
  bash scripts/termux-setup.sh

Stop the loop with Ctrl+C or:  touch data/HALT
"""


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0].lower() if args else ""
    rest = args[1:]
    if not cmd:
        try:
            import fastapi  # noqa: F401

            cmd = "serve"
        except ImportError:
            cmd = "trade"

    if cmd in {"-h", "--help", "help"}:
        print(HELP)
        return
    if cmd in {"setup", "init"}:
        from app.setup_wizard import run_setup

        run_setup(start="--start" in rest or "-y" in rest)
        return
    if cmd in {"trade", "auto", "trader"}:
        from app.cockpit import run_cockpit

        run_cockpit(once=False)
        return
    if cmd in {"once"}:
        from app.cockpit import run_cockpit

        run_cockpit(once=True)
        return
    if cmd in {"test", "selftest", "demo-test"}:
        from app.selftest import run_selftest

        raise SystemExit(run_selftest())
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
