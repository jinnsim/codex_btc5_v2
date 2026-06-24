---
name: live-accounting-bug
description: "codex_btc15_live reports wrong PnL — stop booked before sell confirmation, failed sells never reconciled"
metadata: 
  node_type: memory
  type: project
  originSessionId: 2fdb12d6-e8c1-416a-9a7c-b0aa8febe02a
---

2026-06-23 발견: 라이브 봇 codex_btc15_live 손익 회계 결함. 봇 보고 자산 $115.00(ROI -11.31%) ↔ 실제 CLOB 지갑 $139.6968 (약 -$24.70 과소보고).

근본 원인: runner.py monitor_paper_risk가 `stop_position`(손절=손실)을 실제 `executor.sell` 성공 전에 장부에 확정함. 매도 실패(FAK 미매칭) 시 `reconcile_stop_fill` 미호출 → 'stopped' 고아 포지션. `settle_due`는 stopped를 청산완료로 간주해 실제 만기정산을 반영 안 함. 결과: 청산 실패한 승리 포지션(id1, DOWN +$19.45)이 영구 가짜 손실(-$7.00)로 남고, 그 환상 손실로 max_drawdown 가드가 발동해 봇이 신규 진입 중단(실제론 수익 중).

**Why:** 라이브 검증 게이트가 오염된 증거를 생산 중 → 라이브 PnL은 승격 근거로 못 씀. codex_btc15(trend-v2, t=+2.58)는 페이퍼 기준 최선 후보지만 현실적 체결 반영 후 재검증 필요.

**How to apply:** 5개 패치 + 2차 수정(부분체결 record_exit_fill, 괴리경보 current_cash 기준, 죽은코드 제거) 모두 vc 머신 코드 사본에 TDD로 구현·검증 완료(신규 테스트 21건, 전체 98통과). 과거 데이터 재검증: 장부 $115(갭 -24.69) → $141.46(갭 +1.76, 경보 해제)로 수렴. **단 vc는 사본이고 라이브 봇은 jongjinseok 머신에서 가동 → 그 머신에 배포 후 재베이스라인·재검증 필요.** 배포 전 라이브 규모 확대 금지. 상세는 codex_btc15_live/docs/HANDOFF-2026-06-23-committee-review.md (5/5b절). 남은 low: /book 형식 실측, 임계 튜닝, 얇은호가 손절보류 정책 명문화, ROOT 환경변수화. 위원회 스크립트 ROOT는 jongjinseok 하드코딩이라 vc에선 페이퍼 데이터 안 잡힘.

관련: [[btc5-quant-lab-goal]] [[combined-5m15m-bot]]
