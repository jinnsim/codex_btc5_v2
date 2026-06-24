#!/usr/bin/env bash
set -euo pipefail

pkill -f "codex_btc5_v2 run" || true
pkill -f "codex_btc5_v2/run_forever.sh" || true
screen -S codex_btc5_v2 -X quit || true
