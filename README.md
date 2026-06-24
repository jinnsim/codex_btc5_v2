# codex_btc5_v2

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Mode: paper-only](https://img.shields.io/badge/mode-paper--only-orange.svg)](#)
[![Tests: pytest](https://img.shields.io/badge/tests-pytest-green.svg)](#test)
[![Last commit](https://img.shields.io/github/last-commit/jinnsim/codex_btc5_v2.svg)](https://github.com/jinnsim/codex_btc5_v2/commits/main)
[![Polymarket profile](https://img.shields.io/badge/Polymarket-live%20profile-6A5CFF.svg)](https://polymarket.com/ko/@0x257ae8cb4d7eea2eae996018597c42f587a65d9b-1781352180890)

BTC 5-minute Up/Down paper bot for Polymarket. This project was reconstructed
from `handoff_codex_btc5_v2` and is intentionally **paper-only**: there is no live
order executor in this package, and `LIVE_TRADING_ENABLED=true` fails at startup.

## Live wallet / profile

이 봇이 추적하는 전략의 실제 Polymarket 활동은 아래 공개 프로필에서 볼 수 있다:

- **[Polymarket profile →](https://polymarket.com/ko/@0x257ae8cb4d7eea2eae996018597c42f587a65d9b-1781352180890)**
- Wallet: `0x257ae8cb4d7eea2eae996018597c42f587a65d9b`

> 이 패키지 자체는 paper-only다. 위 프로필은 별도의 라이브 지갑이며 이 코드가
> 자동으로 주문을 내지 않는다.

## 검증 기록 (paper → live)

이 전략이 라이브로 가기까지의 실제 궤적. 아래 페이퍼 수치는
`data/paper_ledger.sqlite3`(및 세션 백업)에서 직접 집계한 값이다.

**1. 섣부른 라이브 — 초기 자금 손실.**
검증되지 않은 초기 버전으로 라이브를 먼저 돌렸고, 실제 지갑 수익률에서
보이듯 초기 투입 자금에 손실이 발생했다. (수치는 위
[Polymarket 프로필](https://polymarket.com/ko/@0x257ae8cb4d7eea2eae996018597c42f587a65d9b-1781352180890)
참조.)

**2. 페이퍼로 후퇴해 검증.**
이후 지금 버전(`trend-v2-5m`)을 **가상 100 pUSD**로 시작해 페이퍼로 돌렸다.
- 최초 페이퍼 시작 자금: **100 pUSD** (2026-06-23, 세션 백업 기준)
- 현재 활성 원장은 **145 pUSD**로 리베이스된 뒤 운영 중 (2026-06-24)
- 현재 활성 원장 실현손익: **+9.63 pUSD** → equity 약 **154.6 pUSD**
- 거래(2026-06-24 ~ 06-25 KST): 판정 83건 중 **승 31 / 손절 49 / 패 3**,
  총 베팅 290.86 pUSD, 스킵 275건(리스크 게이트로 미진입)

> 참고: 중간 리셋·리베이스 때문에 단일 원장에 "100 → 160" 연속 궤적이 그대로
> 남아있지는 않다. 위 수치는 현재 활성 원장 기준의 검증값이다.

**3. 라이브 전환.**
페이퍼에서 양(+)의 실현손익과 리스크 게이트(손절·연속손실 쿨다운) 동작을
확인한 뒤 라이브로 전환했다. 단, **이 repo의 코드는 여전히 paper-only**이며
라이브 실행기는 포함하지 않는다.

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
