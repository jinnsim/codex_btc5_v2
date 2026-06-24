from __future__ import annotations

import threading
import time
from datetime import datetime

import requests

from .config import Settings, settings
from .indicators import fetch_snapshot, format_snapshot
from .evaluation import EvaluationStore, format_accuracy
from .telegram import TelegramClient
from . import polymarket
from .indicators import momentum_direction
from .paper import PaperBook, PaperSummary


def scheduled_digest_key(config: Settings, now: datetime) -> str | None:
    """Return a de-duplication key on wall-clock-aligned schedule boundaries."""
    minutes = config.indicator_schedule_minutes
    if minutes <= 0 or now.minute % minutes != 0:
        return None
    return now.strftime("%Y-%m-%dT%H:%M")


_PAPER_SIDE_BY_SIGNAL = {"RISING": "UP", "FALLING": "DOWN"}
_PAPER_SETTLEMENT_POLL_SECONDS = 15.0


def _maybe_request_resume(client: TelegramClient, book: PaperBook, result: str,
                          now_ts: int, config: Settings = settings) -> None:
    if result not in {"max_drawdown", "daily_loss"}:
        return
    if not book.request_risk_resume(result, now_ts):
        return
    summary = book.summary()
    label = "max_drawdown" if result == "max_drawdown" else "daily_loss"
    client.send(
        f"⚠️ {label} 차단으로 거래 중지 중\n"
        f"현재 equity {summary.equity:,.2f} pUSD | 기준 {summary.initial_cash:,.0f} pUSD "
        f"| ROI {summary.roi_pct:+.2f}%\n"
        "거래를 재개하려면 /resume 을 보내세요. 승인 후 max_drawdown과 daily_loss 기준이 재설정됩니다."
    )


def dynamic_bet_fraction(snapshot, config: Settings = settings) -> float:
    """Scale risk by the weakest of the three aligned momentum conditions."""
    return_score = max(0.0, min(
        1.0,
        (abs(snapshot.return_5m_pct) - config.momentum_return_deadband_pct) / 0.155,
    ))
    rsi_score = max(0.0, min(1.0, abs(snapshot.rsi_14 - 50.0) / 20.0))
    macd_score = max(0.0, min(1.0, abs(snapshot.macd_histogram) / 15.0))
    strength = min(return_score, rsi_score, macd_score)
    spread = config.paper_max_bet_fraction - config.paper_min_bet_fraction
    return config.paper_min_bet_fraction + spread * strength


def run_paper_round(book: PaperBook, snapshot, now_ts: int,
                    config: Settings = settings, session=requests) -> str:
    """One cycle: settle ended rounds, then maybe bet the open 5m round."""
    book.settle_due(now_ts, lambda slug: polymarket.fetch_round_outcome(slug, config, session))
    boundary = now_ts - (now_ts % polymarket.ROUND_SECONDS)
    risk_reason = book.risk_block_reason(
        now_ts,
        config.paper_max_drawdown_pct,
        config.paper_daily_loss_pct,
        config.paper_max_consecutive_losses,
        config.paper_session_utc_offset_hours,
        config.paper_loss_streak_cooldown_minutes * 60,
    )
    if risk_reason is not None:
        book.skip(f"risk-{boundary}", boundary, None, risk_reason)
        return risk_reason
    direction = momentum_direction(snapshot, config.momentum_return_deadband_pct)
    side = _PAPER_SIDE_BY_SIGNAL.get(direction)
    if side is None:
        book.skip(f"mixed-{boundary}", boundary, None, "mixed")
        return "mixed"
    rnd = polymarket.find_open_round(now_ts, config, session)
    if rnd is None:
        book.skip(f"nomarket-{boundary}", boundary, side, "no_market")
        return "no_market"
    if snapshot.candle_close_ts != rnd.start_ts - 1:
        book.skip(f"stale-{boundary}", boundary, side, "stale_signal")
        return "stale_signal"
    if book.has_position(rnd.slug):
        return "dup"
    ask = polymarket.entry_ask_for_side(rnd, side, config, session)
    if ask is None or ask <= 0:
        book.skip(rnd.slug, rnd.start_ts, side, "no_price")
        return "no_price"
    fraction = dynamic_bet_fraction(snapshot, config)
    opened = book.open_position(rnd, side, ask, fraction)
    return "bet" if opened else "no_price"


def monitor_paper_risk(book: PaperBook, now_ts: int, config: Settings = settings,
                       session=requests) -> int:
    """Record executable bids and optionally close at the configured paper stop."""
    recorded = 0
    for position in book.pending_positions(now_ts):
        bid = polymarket.token_best_bid(position["token_id"], config, session)
        if bid is None:
            continue
        if book.record_risk_mark(
            position["id"], now_ts, bid, config.paper_stop_loss_pct
        ):
            recorded += 1
        if not config.paper_stop_loss_enabled:
            continue
        book.stop_position(
            position["id"], now_ts, bid, config.paper_stop_loss_pct,
            config.paper_stop_confirmations,
            config.paper_stop_confirmation_seconds,
        )
    return recorded


def format_paper(summary: PaperSummary, config: Settings | None = None) -> str:
    decided = summary.wins + summary.losses + summary.stops
    win_rate = "n/a" if decided == 0 else f"{summary.wins / decided * 100:.1f}%"
    title = "💵 페이퍼 뱅크롤 (시뮬레이션)"
    unit = "pUSD"
    asset = f"{summary.equity:,.2f} {unit}"
    cash = f"{summary.cash:,.2f}"
    baseline = f"{summary.initial_cash:,.0f}"
    lines = [
        title,
        f"자산 {asset} | 가용현금 {cash} "
        f"| ROI {summary.roi_pct:+.2f}% "
        f"(기준 {baseline})",
        f"베팅 {summary.bets} | 승 {summary.wins} 패 {summary.losses} 손절 {summary.stops} "
        f"승률 {win_rate} | 스킵 {summary.skips}",
    ]
    if summary.last_round is not None:
        lines.append(
            f"직전: {summary.last_side} {summary.last_round.split('-')[-1]} "
            f"pnl {summary.last_pnl:+.2f}"
        )
    lines.append("페이퍼 측정 전용 · 실주문 경로 없음")
    return "\n".join(lines)


def run(config: Settings = settings) -> None:
    config.validate_telegram()
    config.validate_no_live()
    if not config.telegram_enabled:
        raise ValueError("Set TELEGRAM_ENABLED=true to run the Telegram service")

    client = TelegramClient(config)
    evaluations = EvaluationStore(config.evaluation_db)
    paper_book = (
        PaperBook(config.paper_ledger_db, config.paper_initial_cash, config.paper_strategy_id)
        if config.paper_trading_enabled else None
    )
    if paper_book is not None:
        config.validate_paper()
    stop = threading.Event()
    offset = 0
    next_digest = time.monotonic()
    next_paper_settlement = 0.0
    last_schedule_key: str | None = None
    try:
        client.set_commands()  # register the native /command menu; non-fatal on failure
    except requests.RequestException as error:
        print(f"setMyCommands error: {error}")
    try:  # drain stale updates (e.g. PARMA-era) so we don't act on old commands
        drained = requests.get(
            f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates",
            params={"timeout": 0}, timeout=config.http_timeout,
        ).json().get("result", [])
        if drained:
            offset = drained[-1]["update_id"] + 1
    except requests.RequestException:
        pass
    client.send("▶️ codex_btc5_v2 started [📝 PAPER]")
    try:
        while not stop.is_set():
            try:
                now = time.monotonic()
                if paper_book is not None and now >= next_paper_settlement:
                    try:
                        paper_book.settle_due(
                            int(time.time()),
                            lambda slug: polymarket.fetch_round_outcome(slug, config),
                        )
                        if (config.paper_risk_shadow_enabled
                                or config.paper_stop_loss_enabled):
                            monitor_paper_risk(paper_book, int(time.time()), config)
                    except Exception as error:  # settlement is secondary; retry later
                        print(f"paper settlement error: {error}")
                    finally:
                        next_paper_settlement = now + _PAPER_SETTLEMENT_POLL_SECONDS
                offset = client.poll_once(offset)
                schedule_key = scheduled_digest_key(config, datetime.now())
                schedule_due = schedule_key is not None and schedule_key != last_schedule_key
                interval_due = (
                    config.indicator_schedule_minutes <= 0
                    and config.indicator_digest_interval > 0
                    and now >= next_digest
                )
                if schedule_due or interval_due:
                    wall_now = time.time()
                    snapshot = fetch_snapshot(config, now_ts=wall_now)
                    evaluations.resolve_due(snapshot.candle_close_ts, config)
                    evaluations.record(snapshot)
                    message = format_snapshot(snapshot) + "\n\n" + format_accuracy(evaluations.summary())
                    if paper_book is not None:
                        try:
                            result = run_paper_round(paper_book, snapshot, int(wall_now), config)
                            _maybe_request_resume(
                                client, paper_book, result, int(wall_now), config
                            )
                            message += "\n\n" + format_paper(paper_book.summary(), config)
                        except Exception as error:  # paper is secondary; never crash the loop
                            print(f"paper step error: {error}")
                    client.send(message)
                    if schedule_due:
                        last_schedule_key = schedule_key
                    if interval_due:
                        next_digest = now + config.indicator_digest_interval
            except requests.RequestException as error:
                print(f"network error: {error}")
            stop.wait(config.telegram_poll_interval)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.send("⏹️ codex_btc5_v2 stopped")
        except requests.RequestException:
            pass
