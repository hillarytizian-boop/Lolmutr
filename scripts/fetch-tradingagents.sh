#!/usr/bin/env bash
# Clone the official Tauric Research TradingAgents repo (signals source).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/vendor/TradingAgents"
URL="https://github.com/TauricResearch/TradingAgents.git"
mkdir -p "$ROOT/vendor"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only || true
else
  git clone --depth 1 "$URL" "$DEST"
fi
echo "TradingAgents source: $DEST"
