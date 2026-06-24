#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
export PAPER_TRADING_ENABLED="${PAPER_TRADING_ENABLED:-true}"

mkdir -p logs
while true; do
  python3 -m codex_btc5_v2 run 2>&1 | tee -a logs/run.log
  sleep 5
done
