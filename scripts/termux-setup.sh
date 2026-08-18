#!/usr/bin/env bash
# One-shot Termux install: deps, venv, wizard, autotrader.
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
python -m pip install -U pip
python -m pip install -r requirements.txt

echo
echo "Next: paste your LLM key and (optional) Binance keys."
echo "Paper is the default. Live needs the phrase I_UNDERSTAND."
echo
exec python -m app setup --start
