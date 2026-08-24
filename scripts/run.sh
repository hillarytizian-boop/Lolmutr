#!/usr/bin/env bash
# Always use the project venv so Termux system python is not used.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -x .venv/bin/python ]; then
  echo "No .venv yet. Run:  bash scripts/termux-setup.sh"
  exit 1
fi
exec .venv/bin/python -m app "$@"
