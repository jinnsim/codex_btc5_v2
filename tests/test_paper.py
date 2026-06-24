import sqlite3

import pytest

from codex_btc5_v2.paper import PaperBook
from codex_btc5_v2.polymarket import Round


def test_connection_is_closed_after_context(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    with book._connect() as connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def make_round(slug="btc-updown-5m-1781950200", start=1781950200):
    return Round(slug=slug, start_ts=start, end_ts=start + 900,
                 up_token_id="tokUP", down_token_id="tokDOWN", condition_id="0xabc")


def test_risk_mark_records_executable_loss_without_closing(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)
    position = book.pending_positions(1781950300)[0]
    assert book.record_risk_mark(position["id"], 1781950315, bid=0.34,
                                 stop_loss_pct=0.30) is True
    with book._connect() as connection:
        mark = connection.execute("SELECT * FROM paper_risk_marks").fetchone()
        status = connection.execute(
            "SELECT status FROM paper_positions WHERE id = ?", (position["id"],)
        ).fetchone()["status"]
    assert round(mark["return_pct"], 2) == -0.32
    assert mark["would_stop"] == 1
    assert status == "pending"


def test_stop_position_closes_at_bid_and_preserves_shadow_mark(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)
    position = book.pending_positions(1781950300)[0]
    assert book.record_risk_mark(position["id"], 1781950315, bid=0.39,
                                 stop_loss_pct=0.20) is True
    assert book.stop_position(position["id"], 1781950315, bid=0.39,
                              stop_loss_pct=0.20) is True
    with book._connect() as connection:
        mark = connection.execute("SELECT * FROM paper_risk_marks").fetchone()
        stopped = connection.execute("SELECT * FROM paper_positions").fetchone()
    assert mark["would_stop"] == 1
    assert stopped["status"] == "stopped"
    assert stopped["outcome"] == "stop_loss"
    assert stopped["exit_ts"] == 1781950315
    assert stopped["exit_bid"] == 0.39
    assert round(stopped["payout"], 2) == 19.50
    assert round(stopped["pnl"], 2) == -5.50
    assert round(book.current_cash(), 2) == 94.50
    summary = book.summary()
    assert summary.stops == 1
    assert summary.losses == 0


def test_stop_position_ignores_bid_above_threshold(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)
    position = book.pending_positions(1781950300)[0]
    assert book.stop_position(position["id"], 1781950315, bid=0.41,
                              stop_loss_pct=0.20) is False
    assert book.pending_positions(1781950316)[0]["status"] == "pending"


def test_open_position_deducts_stake_and_computes_shares(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    assert book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25) is True
    # stake 25, shares 50, cash now 75
    assert book.current_cash() == 75.0
    assert book.current_equity() == 100.0
    s = book.summary()
    assert s.bets == 1 and s.wins == 0 and s.losses == 0


def test_settle_win_pays_one_per_share(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)  # 50 shares, cash 75
    settled = book.settle_due(1781951200, lambda slug: "UP")
    assert settled == 1
    # payout 50 -> cash 75 + 50 = 125
    assert book.current_cash() == 125.0
    s = book.summary()
    assert s.wins == 1 and s.losses == 0
    assert round(s.realized_pnl, 6) == 25.0


def test_settle_loss_keeps_stake_lost(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)  # cash 75
    book.settle_due(1781951200, lambda slug: "DOWN")
    assert book.current_cash() == 75.0  # stake 25 lost, no payout
    assert book.summary().losses == 1


def test_settle_skips_when_outcome_pending(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)
    assert book.settle_due(1781951200, lambda slug: None) == 0
    assert book.summary().wins == 0 and book.summary().bets == 1


def test_settle_only_resolves_ended_rounds(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)
    # now before end (1781951100) -> nothing due
    assert book.settle_due(1781950400, lambda slug: "UP") == 0


def test_compounding_two_rounds(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)  # cash 75, 50 sh
    book.settle_due(1781951200, lambda slug: "UP")  # cash 125
    r2 = make_round(slug="btc-updown-5m-1781951100", start=1781951100)
    book.open_position(r2, "DOWN", entry_ask=0.5, fraction=0.25)  # stake 31.25
    assert round(book.current_cash(), 2) == 93.75


def test_no_double_bet_same_round(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    assert book.open_position(make_round(), "UP", 0.5, 0.25) is True
    assert book.has_position("btc-updown-5m-1781950200") is True
    assert book.open_position(make_round(), "UP", 0.5, 0.25) is False
    assert book.current_cash() == 75.0  # only deducted once


def test_skip_does_not_change_cash(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.skip("btc-updown-5m-1781950200", 1781950200, None, "mixed")
    assert book.current_cash() == 100.0
    assert book.summary().skips == 1


def test_summary_roi(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.25)
    book.settle_due(1781951200, lambda slug: "UP")  # cash 125
    s = book.summary()
    assert round(s.roi_pct, 4) == 25.0
    assert s.last_round == "btc-updown-5m-1781950200"
    assert s.last_side == "UP"
    assert round(s.last_pnl, 4) == 25.0


def test_stop_requires_persistent_confirmations(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    book.open_position(make_round(), "UP", entry_ask=0.5, fraction=0.10)
    position = book.pending_positions(1781950300)[0]
    for ts in (1781950315, 1781950330):
        book.record_risk_mark(position["id"], ts, 0.39, 0.20)
        assert book.stop_position(position["id"], ts, 0.39, 0.20, 3, 30) is False
    book.record_risk_mark(position["id"], 1781950345, 0.39, 0.20)
    assert book.stop_position(position["id"], 1781950345, 0.39, 0.20, 3, 30) is True


def test_risk_block_after_three_consecutive_losses(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    for index in range(3):
        rnd = make_round(f"btc-updown-5m-{1781950200 + index * 900}",
                         1781950200 + index * 900)
        book.open_position(rnd, "UP", 0.5, 0.02)
        book.settle_due(rnd.end_ts, lambda slug: "DOWN")
    assert book.risk_block_reason(1781954000, 0.50, 0.50, 3, 9) == "loss_streak"
    assert book.risk_block_reason(1781957000, 0.50, 0.50, 3, 9) is None


def test_max_drawdown_resume_approval_resets_peak(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    win = make_round("btc-updown-5m-1781950200", 1781950200)
    book.open_position(win, "UP", 0.5, 0.50)
    book.settle_due(win.end_ts, lambda slug: "UP")  # equity 150, peak 150
    loss = make_round("btc-updown-5m-1781951100", 1781951100)
    book.open_position(loss, "UP", 0.5, 0.50)
    book.settle_due(loss.end_ts, lambda slug: "DOWN")  # equity 75, drawdown 50%

    assert book.risk_block_reason(1781952200, 0.10, 0.90, 99, 9) == "max_drawdown"
    assert book.request_risk_resume("max_drawdown", 1781952200) is True
    assert book.request_risk_resume("max_drawdown", 1781952300) is False
    baseline = book.approve_risk_resume("max_drawdown", 1781952300)
    assert baseline == book.current_equity()
    assert book.risk_block_reason(1781952400, 0.10, 0.90, 99, 9) is None


def test_daily_loss_resume_approval_resets_same_day_loss(tmp_path):
    book = PaperBook(str(tmp_path / "l.sqlite3"), initial_cash=100.0)
    rnd = make_round("btc-updown-5m-1781950200", 1781950200)
    book.open_position(rnd, "UP", 0.5, 0.20)
    book.settle_due(rnd.end_ts, lambda slug: "DOWN")

    assert book.risk_block_reason(1781951200, 0.90, 0.08, 99, 9) == "daily_loss"
    book.request_risk_resume("daily_loss", 1781951200)
    book.approve_risk_resume("daily_loss", 1781951300)
    assert book.risk_block_reason(1781951400, 0.90, 0.08, 99, 9) is None


def test_strategy_id_isolates_old_ledger_rows(tmp_path):
    path = str(tmp_path / "l.sqlite3")
    old = PaperBook(path, 100.0, "old")
    old.open_position(make_round(), "UP", 0.5, 0.25)
    old.settle_due(1781951200, lambda slug: "DOWN")
    new = PaperBook(path, 100.0, "new")
    assert new.current_cash() == 100.0
    assert new.summary().bets == 0
