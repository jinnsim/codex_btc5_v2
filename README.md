# codex_btc5_v2

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Mode: paper-only](https://img.shields.io/badge/mode-paper--only-orange.svg)](#)
[![Tests: pytest](https://img.shields.io/badge/tests-pytest-green.svg)](#test)
[![Last commit](https://img.shields.io/github/last-commit/jinnsim/codex_btc5_v2.svg)](https://github.com/jinnsim/codex_btc5_v2/commits/main)

BTC 5-minute Up/Down paper bot for Polymarket. This project was reconstructed
from `handoff_codex_btc5_v2` and is intentionally **paper-only**: there is no live
order executor in this package, and `LIVE_TRADING_ENABLED=true` fails at startup.

## Requirements

- Python 3.10+
- macOS / Linux (uses `bash` helper scripts for the supervisor loop)

## Setup

```bash
git clone https://github.com/jinnsim/codex_btc5_v2.git
cd codex_btc5_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

The tuned defaults live in `.env.example` and `env/.env.tuned`. Telegram
secrets are **not** committed — to enable the Telegram loop, fill
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your local `.env`, then set
`TELEGRAM_ENABLED=true`.

> `.env` is git-ignored. Keep real secrets there only — never in `.env.example`
> or `env/.env.tuned`, which are public.

## Run

```bash
python -m codex_btc5_v2 once        # print the current 5m indicator snapshot
python -m codex_btc5_v2 paper-once  # run a single paper-trading round
python -m codex_btc5_v2 run         # run the continuous loop
```

To keep the loop running with auto-restart (logs to `logs/run.log`):

```bash
./run_forever.sh   # supervisor loop
./stop.sh          # stop the loop
```

The imported sample state lives in `data/paper_ledger.sqlite3` and
`data/evaluations.sqlite3` (both git-ignored). The original handoff documents
are under `handoff/`, and the project memory files are under `memory/`.

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```
