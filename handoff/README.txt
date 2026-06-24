codex_btc5_v2 핸드오프 패키지 (2026-06-23)
- 먼저 HANDOFF-codex_btc5_v2-tuning-20260623.md 를 읽으세요.
- env/.env.tuned: 튜닝된 설정. TELEGRAM_BOT_TOKEN/CHAT_ID는 보안상 마스킹돼 있으니
  실제 값으로 채운 뒤 대상 머신의 codex_btc5_v2/.env 로 반영하세요.
- data/: 현재 표본(paper_ledger.sqlite3)·아카이브 세션·정확도(evaluations). 같은 표본을
  이어가려면 대상 codex_btc5_v2/data/ 에 복사. 새로 시작하면 복사 생략.
- memory/: 프로젝트 메모리 원본(대상 머신 Claude 메모리에 반영 가능).
- 주의: codex_btc5_v2 코드베이스가 대상 머신에 있어야 실행됩니다(없으면 프로젝트 별도 전송).
- 시크릿(텔레그램 토큰 등)은 이 패키지에 포함하지 않았습니다. 외부 채널 전송 시 주의.
