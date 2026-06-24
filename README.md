# codex_btc5_v2

BTC 5-minute Up/Down paper bot for Polymarket. This project was reconstructed
from `handoff_codex_btc5_v2` and is intentionally paper-only: there is no live
order executor in this package, and `LIVE_TRADING_ENABLED=true` fails at startup.

## Setup

```bash
cd /Users/jongjinseok/Documents/polymarket_v2/codex_btc5_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The handoff tuning is in `.env`, `.env.example`, and `env/.env.tuned`.
Telegram secrets were not included in the handoff. To run the Telegram loop,
fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then set
`TELEGRAM_ENABLED=true`.

## Run

```bash
python -m codex_btc5_v2 once
python -m codex_btc5_v2 paper-once
python -m codex_btc5_v2 run
```

The imported sample state lives in `data/paper_ledger.sqlite3` and
`data/evaluations.sqlite3`. The original handoff documents are under
`handoff/`, and the project memory files are under `memory/`.

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```
