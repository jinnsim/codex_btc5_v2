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

## 지금까지 시도한 알고리즘과 실패 원인

이 프로젝트(및 자매 실험)에서 검토했던 전략들의 현재 판정과 정체 원인 기록.
명확히 폐기된 것은 MM 계열, 검증 기준을 통과하지 못한 것은 `btc5_quant`이며,
나머지는 실패 확정이라기보다 **미검증·보류·드라이런** 단계다.

| 전략 · 시스템 | 현재 판정 | 핵심 실패 또는 정체 원인 |
| --- | --- | --- |
| 일반 Market Making | 폐기 | 비용 차감 후 엣지 부족, 역선택, 재고 위험, 체결 가정 과대평가 |
| Selective MM | 폐기 / 사실상 중단 | 시장 선별로도 구조적 MM 위험을 제거하지 못함 |
| `btc5_quant` | 검증 탈락, 드라이런 유지 | 예측 신호가 실제 주문 가능 수익으로 연결되지 않음 |
| MACD + RSI 5분 | 라이브 관찰 중, 미검증 | 후행성, 짧은 만기, Polymarket 가격구조 미반영 |
| Settlement Sniping | 연구 · 보조 전략 | "결과가 거의 확정"이라는 가정이 실제로는 자주 깨짐 |
| Complete-set / Combo 차익거래 | 탐지 · 페이퍼 단계 | 표시 차익이 수수료 · 슬리피지 · 지연 후 사라짐 |
| Observatory | 전략 아님 (검증 인프라) | 데이터 · 상태 정합성 문제를 해결한 뒤 드라이런 중 |
| TradingAgents / LLM 에이전트 | 주력 채택 보류 | 재현성 · 지연 · 환각 · 실행 검증 부족 |
| 반복매매 복리 모델 | 아이디어 단계 | 반복 횟수가 엣지를 만들지 않으며 손실도 누적됨 |
| 레버리지 전략 | 보류 | Polymarket 구조와 부적합, 파산 위험만 증폭 |
| ARAM-C | 별도 미국주식 프로젝트 | 실패가 아니라 v1.0 동결 후 백테스트 준비 단계 |

핵심 교훈: **백테스트·신호 수준의 엣지가 실제 주문 가능 수익으로 이어지지 않는다.**
수수료·슬리피지·지연·역선택을 차감하면 표시상의 우위는 대부분 사라지며,
그래서 이 패키지는 라이브 주문 없이 paper-only로 유지된다.
