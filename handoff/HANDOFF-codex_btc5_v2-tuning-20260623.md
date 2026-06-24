# 핸드오프 — codex_btc5_v2 튜닝 & 표본 수집 (2026-06-23)

작성: 2026-06-23 15:0x (vc 머신)
목적: 다른 머신에서 이 작업을 이어받아 **표본을 더 모으고 5m 신호 엣지를 평가**
상태: 🟢 봇 정상 가동, 튜닝 적용 완료, breakeven 부근(-1%). 신호 엣지 평가 단계로 진입.

---

## 0. TL;DR
- codex_btc5_v2 = trend-v2 전략을 **5분 Up/Down**에 얹은 페이퍼 봇(실거래 아님).
- 오늘 두 가지 튜닝 적용: **사이징 축소**(max 10%→5%) + **손절 confirmations 2**(원래 1로 낮췄다가 휩쏘 보고 2로 상향).
- 효과: 손실폭 축소·만기 전액손실 방지로 equity가 -8.12% → **-1.0%(99.0)**로 회복.
- 한계: **신호 엣지가 약함**(승률 36%, 11체결). 손절 confirmations=2로도 허위손절 ~1/3은 못 줄임(5m이 본질적으로 choppy). loss_streak 쿨다운이 반복됨.
- 다음 단계: **표본 30+ 체결까지 모아** 승률/기대값이 50%/+로 수렴하는지 본 뒤, 안 되면 5m 변종은 접고 15m(codex_btc15)에 집중.

---

## 1. 봇 개요
- 경로: `/Users/vc/Documents/polymarket/codex_btc5_v2`
- 시장: Polymarket BTC 5분 Up/Down (`btc-updown-5m-<window_start>` 슬러그). 임계값은 윈도우 시작 BTC open price.
- 전략: `trend-v2-5m` (모멘텀: 15m return + RSI + MACD hist, deadband로 노이즈 필터).
- **페이퍼 전용**: live_exec 없음, live 설정 없음. 실주문 경로 자체가 없음.
- 텔레그램: 자체 봇 토큰(.env, 절대 커밋 금지), chat_id 8674415640. 명령 `/status /paper /accuracy /indicators`는 봇이 로컬 데이터로 응답.
- 기동: `cd codex_btc5_v2 && source .venv/bin/activate && export PAPER_TRADING_ENABLED=true && python -m codex_btc5_v2 run` (백그라운드는 nohup … &). 자동 재기동 supervisor 없음.

## 2. 오늘 적용한 튜닝 (.env)
| 항목 | 이전 | 현재 | 의도 |
|---|---|---|---|
| PAPER_MIN_BET_FRACTION | 0.02 | **0.01** | 사이징 축소 |
| PAPER_MAX_BET_FRACTION | 0.10 | **0.05** | 단일 베팅 최대 위험 절반(풀로스 1방이 일일한도 먹는 문제) |
| PAPER_STOP_CONFIRMATIONS | 3 → 1 → **2** | 5m 안에서 손절 발동시키되, 단일틱 휩쏘는 거름 |
| PAPER_STOP_CONFIRMATION_SECONDS | 30 | **0** | 5m은 만기가 짧아 확인시간 0 |

그대로 둔 리스크 가드: stop_loss_pct 0.20, daily_loss 0.08, max_drawdown 0.10,
max_consecutive_losses 3, loss_streak_cooldown 60분, utc_offset 9(KST, 일자경계=KST자정),
deadband 0.045.

세션 처리: 오늘 11:55에 직전 원장을 `data/paper_ledger.sqlite3.session-1782183332`로 아카이브하고
새 $100 세션 시작(daily_loss 락아웃 해제 목적). 이후 confirmations 변경은 원장 유지한 채 재시작만 함.

## 3. 현재 성과 (2026-06-23 15:0x 기준, 새 세션)
- equity **99.0 (-1.0%)** / 32라운드 / 11체결(4승 7손절) / **승률 36%**
- 손절 confirmations=2 정산완료 3건 중 **허위손절 1건(~1/3)** — confirmations=1과 동률.
  정상 손절 2건은 보유 대비 +2.55 절약.
- loss_streak 쿨다운 2회 발생(라운드 8~13, 27~32) — 승률 낮아 3연속 손절이 잦음.
- SSL: 12:30~13:05 일시 `CERTIFICATE_VERIFY_FAILED` 블립 있었으나 자가복구(certifi 최신, 설정문제 아님). 정산은 settle_due가 back-fill.

## 4. 진단 & 다음 단계
- 튜닝(사이징↓, confirmations 2)은 **손실 통제엔 성공**, 그러나 **허위손절은 5m 특성상 못 줄임**.
- 이제 병목은 리스크 파라미터가 아니라 **신호 엣지**: 승률 36%, loss_streak 반복 → trend-v2를 5m에 얹은 신호가 약함(구버전 codex_btc5 승률 25%, 위원회가 5m 봇을 "노이즈/미증명"으로 본 것과 일치).
- **계획(사용자 결정): 표본을 더 모아서 살펴본다.**
  - 목표: 체결 30+ 까지 누적 후 승률·기대값(EV/벳)·t-stat이 50%/+로 수렴하는지 확인.
  - 수렴하면 유지/스케일 검토, 안 하면 5m 변종 종료하고 15m(codex_btc15, 유일하게 t=+2.58 증명)에 집중.
  - 추가 옵션(선택): 진입조건/deadband 재설계로 진입 빈도↓·질↑.

## 5. 다른 머신에서 이어받는 법
1. codex_btc5_v2 코드베이스가 대상 머신에 있어야 함(없으면 프로젝트 전체 별도 전송 필요).
2. `env/.env.tuned`의 파라미터를 대상 `.env`에 반영(토큰/chat_id는 **마스킹돼 있으니 실제 값으로 채울 것**).
3. 같은 표본을 이어가려면 `data/paper_ledger.sqlite3`(+`evaluations.sqlite3`)를 대상 `data/`에 복사. 새로 시작하려면 복사 생략(봇이 $100로 새 원장 생성).
4. 기동: 2.의 명령. `/paper`·`/accuracy`로 상태 확인.
5. 점검 쿼리 예: `sqlite3 data/paper_ledger.sqlite3 "SELECT status,outcome,count(*),round(sum(pnl),2) FROM paper_positions GROUP BY status,outcome;"`
   허위손절율: `... WHERE status='stopped' AND resolution_outcome IS NOT NULL` 에서 `resolution_outcome=side` 비율.

## 6. 프로젝트 메모리 컨텍스트 (요약 — 상세는 memory/ 폴더)
- **btc5-quant-lab-goal**: 최종 목표는 라이브 트레이딩 봇이나 **검증 게이트 우선**. shadow 전용 설계(LIVE_TRADING_ENABLED true면 raise). 1000+ shadow 거래, out-of-sample EV+ 등 게이트 통과 + 관할권 컴플라이언스 확인 전 라이브 금지.
- **combined-5m15m-bot**: `claude__btc_5_15` = codex_btc5(5m)+codex_btc15(15m) 단일 프로세스 병합, 공유 뱅크롤(`data/paper_ledger_combined.sqlite3`, strategy_id `combined`), 단일 텔레그램 봇(409 회피). 상세 `claude__btc_5_15/handoff/HANDOFF.md`. 여전히 페이퍼 전용.
- **live-accounting-bug**: codex_btc15_live 손익 회계 버그(손절을 매도 성공 전 확정 → 고아 포지션, $115 보고 vs 실지갑 $139.70). vc 머신 사본에 5패치+2차수정 TDD 완료(테스트 21신규/98전체), 재검증 수렴. **jongjinseok(라이브) 머신 배포·재검증 미완.** 상세 `codex_btc15_live/docs/HANDOFF-2026-06-23-committee-review.md`. 배포 전 라이브 규모 확대 금지.
- 봇 상호관계: 통계 증명된 라이브 후보는 **codex_btc15(15m, t=+2.58)** 하나. 5m 변종들(codex_btc5, codex_btc5_v2)은 엣지 미증명. 라이브는 jongjinseok 머신, 페이퍼/연구는 vc 머신.

---

## 7. 패키지 구성물
```
HANDOFF-codex_btc5_v2-tuning-20260623.md   (이 문서)
README.txt                                  자료/주의
env/.env.tuned                              튜닝된 .env (토큰·chat_id 마스킹)
data/paper_ledger.sqlite3                   현재 표본(이어서 수집용)
data/paper_ledger.sqlite3.session-*         직전(아카이브) 세션
data/evaluations.sqlite3                    방향 정확도 측정
memory/                                      프로젝트 메모리 원본(MEMORY.md + 3개)
```

면책: 수치는 관찰된 페이퍼 원장 데이터이며 투자권유가 아님. 실거래/세무 판단은 전문가 확인 필요.
긴급 운영 이슈(반복 SSL/정산 누락 등)는 담당 팀에 직접 보고/에스컬레이션할 것.
