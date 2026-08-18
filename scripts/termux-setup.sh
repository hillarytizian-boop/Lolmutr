#!/usr/bin/env bash
# One-shot Termux install: lean deps (no pydantic/Rust), wizard, autotrader.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

is_termux=0
if [ -n "${TERMUX_VERSION-}" ] || [ -d /data/data/com.termux/files ]; then
  is_termux=1
fi

if [ "$is_termux" -eq 1 ]; then
  echo "Termux detected — installing python + git"
  pkg update -y || true
  pkg install -y python git
  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock || true
    echo "Wake lock on (install termux-api if this failed)."
  fi
fi

PY="python3"
command -v python3 >/dev/null 2>&1 || PY="python"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

# Prefer wheels only. Termux Python 3.14 cannot compile pydantic-core
# (Rust target aarch64-unknown-linux-android is not rustup-supported).
python -m pip install --upgrade pip setuptools wheel
# httpx + dotenv only. FastAPI/pydantic need Rust on Termux Python 3.14.
python -m pip install --prefer-binary "httpx>=0.27.0" "python-dotenv>=1.0.0" "rich>=13.7.0"

python -c "import httpx, dotenv; print('core deps ok', httpx.__version__)"

echo "Fetching official TradingAgents (signal source)..."
bash "$ROOT/scripts/fetch-tradingagents.sh" || echo "clone failed — firm still runs from bundled official prompts"

echo
echo "Use the venv python, not Termux system python:"
echo "  . .venv/bin/activate"
echo "  python -m app setup"
echo "or:  bash scripts/run.sh setup"
echo
exec .venv/bin/python -m app setup --start
