---
name: btc5-quant-lab-goal
description: "btc5_quant_lab project direction — shadow lab now, live trading bot is the end goal, validation gate first"
metadata: 
  node_type: memory
  type: project
  originSessionId: 236a7a79-764e-4e61-a17b-1bbdbf3cdcce
---

`btc5_quant_lab` (Polymarket BTC 5-minute Up/Down markets). The user stated on 2026-06-19 that the **final goal is a live trading bot**, but chose to pursue the **validation gate first** before any live execution work.

The project is shadow-only by design: `app/config.py` raises if `LIVE_TRADING_ENABLED=true`, and there is no order-placement path. Live trading must not be enabled until the SPEC promotion gate passes out-of-sample AND a jurisdiction/compliance check is done (Polymarket is restricted in several jurisdictions).

**How to apply:** Build toward live capability via the promotion gate (`research/promotion_gate.py`, `python app/main.py gate`): data gap rate, stale rate, resolution-label reliability, 1000+ shadow trades, positive out-of-sample fill-adjusted EV. Remaining gate TODO: cross-check Binance-close resolution against the official Polymarket oracle (closed updown markets returned 0 from the gamma `closed=true` query — needs another endpoint). Do not add order placement or flip the safety flag without explicit user confirmation.

Threshold model: BTC5 Up/Down markets have no dollar threshold; it is the BTC open price at the window start (from the `btc-updown-5m-<window_start>` slug timestamp, via Binance 1m klines).
