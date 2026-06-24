---
name: combined-5m15m-bot
description: claude__btc_5_15 merged 5m+15m paper-trading bot with one shared bankroll and one Telegram bot
metadata: 
  node_type: memory
  type: project
  originSessionId: 11b1056c-1e18-4130-ba14-443be45714c6
---

`/Users/vc/Documents/polymarket/claude__btc_5_15` merges codex_btc5 (5m) and
codex_btc15 (15m) into one process. Built 2026-06-22.

Architecture:
- Both packages copied in unchanged for their interval-specific signal + bet
  sizing. New `combined/` orchestrator owns a single Telegram bot (avoids the
  getUpdates 409 conflict two pollers on one token would cause).
- Shared bankroll (user chose this over separate ledgers): both engines bet
  from ONE pooled ledger `data/paper_ledger_combined.sqlite3`, strategy_id
  `combined`, using codex_btc15's PaperBook (sums cash/equity/ROI/risk across
  engines). Account-level risk + stops unified under `COMBINED_PAPER_*`
  (defaults = btc15 trend-v2 policy). Direction-accuracy stays per-interval
  (`evaluations_5m/15m.sqlite3`).
- One Telegram bot (a NEW bot, distinct token from the two original bots), common
  chat id 8674415640. Token lives in `.env`, never commit it. Run: `python3 -m
  combined run` (or run_combined.sh); dry runs: `once` / `paper-once`.

Full handoff doc: `claude__btc_5_15/handoff/HANDOFF.md` (architecture, decisions,
the 5m format_snapshot bug+fix, shared-bankroll mechanics, compounding/variance-drain
analysis, ledger_report.py usage, ops, open items). Read it first next session.

Related: [[btc5-quant-lab-goal]]. Still shadow/paper only — no live orders.
