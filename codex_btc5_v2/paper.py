from __future__ import annotations

import sqlite3
import math
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

from .polymarket import Round


@dataclass(frozen=True)
class PaperSummary:
    cash: float
    equity: float
    initial_cash: float
    bets: int
    wins: int
    losses: int
    stops: int
    voids: int
    skips: int
    realized_pnl: float
    roi_pct: float
    last_round: str | None
    last_side: str | None
    last_pnl: float | None


class PaperBook:
    def __init__(self, path: str, initial_cash: float, strategy_id: str = "default"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_cash = float(initial_cash)
        self.strategy_id = strategy_id.strip()
        self._init_db()

    @staticmethod
    def persisted_initial_cash(path: str, strategy_id: str) -> float | None:
        """Return an existing strategy baseline without creating a new account."""
        db_path = Path(path)
        if not db_path.exists():
            return None
        connection = sqlite3.connect(db_path, timeout=10)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='paper_strategy_accounts'"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute(
                "SELECT initial_cash FROM paper_strategy_accounts WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
            return float(row[0]) if row is not None else None
        finally:
            connection.close()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_slug TEXT NOT NULL UNIQUE,
                    boundary_ts INTEGER NOT NULL,
                    end_ts INTEGER NOT NULL,
                    side TEXT,
                    token_id TEXT,
                    entry_ask REAL,
                    shares REAL,
                    stake REAL,
                    status TEXT NOT NULL,
                    outcome TEXT,
                    payout REAL,
                    pnl REAL,
                    exit_ts INTEGER,
                    exit_bid REAL
                )
            """)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(paper_positions)")
            }
            if "token_id" not in columns:
                connection.execute("ALTER TABLE paper_positions ADD COLUMN token_id TEXT")
            if "exit_ts" not in columns:
                connection.execute("ALTER TABLE paper_positions ADD COLUMN exit_ts INTEGER")
            if "exit_bid" not in columns:
                connection.execute("ALTER TABLE paper_positions ADD COLUMN exit_bid REAL")
            if "strategy_id" not in columns:
                connection.execute(
                    "ALTER TABLE paper_positions ADD COLUMN strategy_id TEXT NOT NULL DEFAULT 'legacy'"
                )
            # Stop-loss verification: track each stopped position's eventual
            # resolution and the hypothetical hold-to-resolution PnL, so a stop
            # that cuts winners (false stop) stays measurable per strategy.
            for name, kind in (("resolution_outcome", "TEXT"),
                               ("resolution_ts", "INTEGER"), ("hold_pnl", "REAL")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE paper_positions ADD COLUMN {name} {kind}")
            # Partial-exit tracking: a live stop SELL may only partially fill (FAK).
            # Accumulate sold shares / salvaged proceeds so the residual stays open
            # and settles at resolution instead of being orphaned.
            for name in ("exited_shares", "exit_proceeds"):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE paper_positions ADD COLUMN {name} REAL NOT NULL DEFAULT 0"
                    )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS paper_risk_marks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    observed_ts INTEGER NOT NULL,
                    bid REAL NOT NULL,
                    return_pct REAL NOT NULL,
                    would_stop INTEGER NOT NULL,
                    UNIQUE(position_id, observed_ts),
                    FOREIGN KEY(position_id) REFERENCES paper_positions(id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS paper_strategy_accounts (
                    strategy_id TEXT PRIMARY KEY,
                    initial_cash REAL NOT NULL,
                    created_ts INTEGER NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS paper_risk_controls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    risk_kind TEXT NOT NULL,
                    requested_ts INTEGER NOT NULL,
                    approved_ts INTEGER,
                    baseline_equity REAL
                )
            """)
            row = connection.execute(
                "SELECT initial_cash FROM paper_strategy_accounts WHERE strategy_id = ?",
                (self.strategy_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO paper_strategy_accounts(strategy_id, initial_cash, created_ts) "
                    "VALUES (?, ?, CAST(strftime('%s','now') AS INTEGER))",
                    (self.strategy_id, self.initial_cash),
                )
            elif abs(float(row["initial_cash"]) - self.initial_cash) > 1e-9:
                raise ValueError(
                    f"initial cash for strategy {self.strategy_id!r} is already "
                    f"persisted as {float(row['initial_cash']):g}"
                )

    def current_cash(self) -> float:
        with self._connect() as connection:
            row = connection.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN status IN ('pending','won','lost','stopped')
                                      THEN stake ELSE 0 END), 0) AS staked,
                    COALESCE(SUM(CASE WHEN status IN ('won','lost','stopped')
                                      THEN payout ELSE 0 END), 0) AS paid,
                    COALESCE(SUM(CASE WHEN status = 'pending'
                                      THEN exit_proceeds ELSE 0 END), 0) AS salvaged
                FROM paper_positions WHERE strategy_id = ?
            """, (self.strategy_id,)).fetchone()
        return (self.initial_cash - float(row["staked"]) + float(row["paid"])
                + float(row["salvaged"]))

    def current_equity(self) -> float:
        """Cost-basis equity; pending positions retain their entry value."""
        with self._connect() as connection:
            row = connection.execute("""
                SELECT COALESCE(SUM(stake), 0) AS pending_value
                FROM paper_positions
                WHERE strategy_id = ? AND status = 'pending'
            """, (self.strategy_id,)).fetchone()
        return self.current_cash() + float(row["pending_value"])

    def has_position(self, round_slug: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM paper_positions WHERE round_slug = ? AND strategy_id = ?",
                (round_slug, self.strategy_id),
            ).fetchone()
        return row is not None

    def open_position(self, rnd: Round, side: str, entry_ask: float, fraction: float) -> bool:
        if entry_ask is None or not math.isfinite(entry_ask) or not (0 < entry_ask <= 1):
            return False
        stake = self.current_cash() * fraction
        if stake <= 0:
            return False
        shares = stake / entry_ask
        with self._connect() as connection:
            cursor = connection.execute("""
                INSERT OR IGNORE INTO paper_positions (
                    round_slug, boundary_ts, end_ts, side, token_id,
                    entry_ask, shares, stake, status, strategy_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (
                rnd.slug, rnd.start_ts, rnd.end_ts, side,
                rnd.up_token_id if side == "UP" else rnd.down_token_id,
                entry_ask, shares, stake, self.strategy_id,
            ))
            return cursor.rowcount == 1

    def open_position_live(self, rnd: Round, side: str, entry_price: float,
                           shares: float, stake: float) -> bool:
        """Record a position from a REAL fill (actual avg price / shares / USDC spent)."""
        if not (entry_price > 0 and shares > 0 and stake > 0):
            return False
        with self._connect() as connection:
            cursor = connection.execute("""
                INSERT OR IGNORE INTO paper_positions (
                    round_slug, boundary_ts, end_ts, side, token_id,
                    entry_ask, shares, stake, status, strategy_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (
                rnd.slug, rnd.start_ts, rnd.end_ts, side,
                rnd.up_token_id if side == "UP" else rnd.down_token_id,
                entry_price, shares, stake, self.strategy_id,
            ))
            return cursor.rowcount == 1

    def pending_positions(self, now_ts: int) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM paper_positions "
                "WHERE strategy_id = ? AND status = 'pending' "
                "AND end_ts > ? AND token_id IS NOT NULL",
                (self.strategy_id, now_ts),
            ).fetchall()

    def record_risk_mark(self, position_id: int, observed_ts: int, bid: float,
                         stop_loss_pct: float) -> bool:
        if not math.isfinite(bid) or not (0 < bid <= 1):
            return False
        with self._connect() as connection:
            position = connection.execute(
                "SELECT entry_ask FROM paper_positions WHERE id = ? AND status = 'pending'",
                (position_id,),
            ).fetchone()
            if position is None:
                return False
            return_pct = bid / float(position["entry_ask"]) - 1.0
            cursor = connection.execute("""
                INSERT OR IGNORE INTO paper_risk_marks (
                    position_id, observed_ts, bid, return_pct, would_stop
                ) VALUES (?, ?, ?, ?, ?)
            """, (position_id, observed_ts, bid, return_pct,
                  int(return_pct <= -stop_loss_pct)))
            return cursor.rowcount == 1

    def stop_should_fire(self, position_id: int, observed_ts: int, bid: float,
                         stop_loss_pct: float, confirmations: int = 1,
                         confirmation_seconds: int = 0) -> bool:
        """Pure stop decision: would this pending position stop now? No DB write.

        Live callers must place the real SELL first and only commit the stop on a
        confirmed fill (record_live_stop); committing before the fill is what
        orphaned positions whose SELL failed (the 2026-06-23 accounting bug)."""
        if not math.isfinite(bid) or not (0 < bid <= 1):
            return False
        with self._connect() as connection:
            position = connection.execute(
                "SELECT entry_ask FROM paper_positions "
                "WHERE id = ? AND status = 'pending'",
                (position_id,),
            ).fetchone()
            if position is None:
                return False
            return_pct = bid / float(position["entry_ask"]) - 1.0
            if return_pct > -stop_loss_pct:
                return False
            marks = connection.execute("""
                SELECT observed_ts, would_stop FROM paper_risk_marks
                WHERE position_id = ? ORDER BY observed_ts DESC LIMIT ?
            """, (position_id, confirmations)).fetchall()
            if len(marks) < confirmations or not all(row["would_stop"] for row in marks):
                return False
            if int(marks[0]["observed_ts"]) - int(marks[-1]["observed_ts"]) < confirmation_seconds:
                return False
            return True

    def stop_position(self, position_id: int, observed_ts: int, bid: float,
                      stop_loss_pct: float, confirmations: int = 1,
                      confirmation_seconds: int = 0) -> bool:
        """Close a pending paper position at the observed executable bid.

        For paper/dry mode (no real fill). Live callers use record_live_stop."""
        if not self.stop_should_fire(position_id, observed_ts, bid, stop_loss_pct,
                                     confirmations, confirmation_seconds):
            return False
        with self._connect() as connection:
            position = connection.execute(
                "SELECT shares, stake FROM paper_positions "
                "WHERE id = ? AND status = 'pending'",
                (position_id,),
            ).fetchone()
            if position is None:
                return False
            payout = float(position["shares"]) * bid
            pnl = payout - float(position["stake"])
            cursor = connection.execute("""
                UPDATE paper_positions
                SET status = 'stopped', outcome = 'stop_loss', payout = ?, pnl = ?,
                    exit_ts = ?, exit_bid = ?
                WHERE id = ? AND status = 'pending'
            """, (payout, pnl, observed_ts, bid, position_id))
            return cursor.rowcount == 1

    def record_exit_fill(self, position_id: int, filled_shares: float, proceeds: float,
                         observed_ts: int, exit_bid: float) -> str | None:
        """Record a CONFIRMED real SELL fill against a pending position.

        Accumulates sold shares / salvaged USDC. If the remaining shares are now
        exhausted the position is committed as 'stopped' (payout = total proceeds);
        otherwise it stays 'pending' so the residual settles at resolution. Returns
        'stopped', 'partial', or None (no such pending position)."""
        epsilon = 1e-6
        with self._connect() as connection:
            position = connection.execute(
                "SELECT shares, stake, exited_shares, exit_proceeds "
                "FROM paper_positions WHERE id = ? AND status = 'pending'",
                (position_id,),
            ).fetchone()
            if position is None:
                return None
            new_exited = float(position["exited_shares"]) + float(filled_shares)
            new_proceeds = float(position["exit_proceeds"]) + float(proceeds)
            remaining = float(position["shares"]) - new_exited
            if remaining <= epsilon:
                pnl = new_proceeds - float(position["stake"])
                connection.execute("""
                    UPDATE paper_positions
                    SET status = 'stopped', outcome = 'stop_loss', payout = ?, pnl = ?,
                        exit_ts = ?, exit_bid = ?, exited_shares = ?, exit_proceeds = ?
                    WHERE id = ? AND status = 'pending'
                """, (new_proceeds, pnl, observed_ts, exit_bid, new_exited,
                      new_proceeds, position_id))
                return "stopped"
            connection.execute("""
                UPDATE paper_positions
                SET exited_shares = ?, exit_proceeds = ?, exit_ts = ?, exit_bid = ?
                WHERE id = ? AND status = 'pending'
            """, (new_exited, new_proceeds, observed_ts, exit_bid, position_id))
            return "partial"

    def record_live_stop(self, position_id: int, exit_bid: float, payout: float,
                         observed_ts: int) -> bool:
        """Commit a full-fill stop from a CONFIRMED real SELL. Thin wrapper over
        record_exit_fill that treats the whole position as exited."""
        with self._connect() as connection:
            position = connection.execute(
                "SELECT shares, exited_shares FROM paper_positions "
                "WHERE id = ? AND status = 'pending'",
                (position_id,),
            ).fetchone()
            if position is None:
                return False
            remaining = float(position["shares"]) - float(position["exited_shares"])
        return self.record_exit_fill(position_id, remaining, payout,
                                     observed_ts, exit_bid) == "stopped"

    def repair_unfilled_stop(self, position_id: int, outcome: str) -> bool:
        """Re-settle a position wrongly marked 'stopped' though its real SELL never
        filled: book the actual round resolution ($1/share win, $0 loss)."""
        if outcome not in ("UP", "DOWN"):
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT side, shares, stake FROM paper_positions "
                "WHERE id = ? AND status = 'stopped'",
                (position_id,),
            ).fetchone()
            if row is None:
                return False
            won = outcome == row["side"]
            payout = float(row["shares"]) if won else 0.0
            pnl = payout - float(row["stake"])
            cursor = connection.execute("""
                UPDATE paper_positions
                SET status = ?, outcome = ?, payout = ?, pnl = ?,
                    resolution_outcome = ?,
                    resolution_ts = COALESCE(resolution_ts, exit_ts),
                    hold_pnl = ?
                WHERE id = ? AND status = 'stopped'
            """, ("won" if won else "lost", outcome, payout, pnl, outcome, pnl, position_id))
            return cursor.rowcount == 1

    def skip(self, round_slug: str, boundary_ts: int, side: str | None, reason: str) -> None:
        with self._connect() as connection:
            connection.execute("""
                INSERT OR IGNORE INTO paper_positions (
                    round_slug, boundary_ts, end_ts, side, status, outcome, strategy_id
                ) VALUES (?, ?, ?, ?, 'skipped', ?, ?)
            """, (round_slug, boundary_ts, boundary_ts, side, reason, self.strategy_id))

    def request_risk_resume(self, risk_kind: str, requested_ts: int) -> bool:
        """Record one active operator-approval request for a hard risk block."""
        with self._connect() as connection:
            active = connection.execute("""
                SELECT 1 FROM paper_risk_controls
                WHERE strategy_id = ? AND risk_kind = ? AND approved_ts IS NULL
                ORDER BY requested_ts DESC LIMIT 1
            """, (self.strategy_id, risk_kind)).fetchone()
            if active is not None:
                return False
            connection.execute("""
                INSERT INTO paper_risk_controls(strategy_id, risk_kind, requested_ts)
                VALUES (?, ?, ?)
            """, (self.strategy_id, risk_kind, int(requested_ts)))
            return True

    def approve_risk_resume(self, risk_kind: str, approved_ts: int) -> float:
        """Approve a hard risk-block resume and reset that risk's peak baseline."""
        baseline = self.current_equity()
        with self._connect() as connection:
            row = connection.execute("""
                SELECT id FROM paper_risk_controls
                WHERE strategy_id = ? AND risk_kind = ? AND approved_ts IS NULL
                ORDER BY requested_ts DESC, id DESC LIMIT 1
            """, (self.strategy_id, risk_kind)).fetchone()
            if row is None:
                connection.execute("""
                    INSERT INTO paper_risk_controls(
                        strategy_id, risk_kind, requested_ts, approved_ts, baseline_equity
                    ) VALUES (?, ?, ?, ?, ?)
                """, (self.strategy_id, risk_kind, int(approved_ts), int(approved_ts), baseline))
            else:
                connection.execute("""
                    UPDATE paper_risk_controls
                    SET approved_ts = ?, baseline_equity = ?
                    WHERE id = ?
                """, (int(approved_ts), baseline, row["id"]))
        return baseline

    def latest_risk_resume(self, risk_kind: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("""
                SELECT approved_ts, baseline_equity FROM paper_risk_controls
                WHERE strategy_id = ? AND risk_kind = ? AND approved_ts IS NOT NULL
                ORDER BY approved_ts DESC, id DESC LIMIT 1
            """, (self.strategy_id, risk_kind)).fetchone()

    def risk_block_reason(self, now_ts: int, max_drawdown_pct: float,
                          daily_loss_pct: float, max_consecutive_losses: int,
                          utc_offset_hours: int = 0,
                          loss_streak_cooldown_seconds: int = 3600) -> str | None:
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT end_ts, exit_ts, pnl FROM paper_positions
                WHERE strategy_id = ? AND status IN ('won','lost','stopped')
                ORDER BY end_ts, id
            """, (self.strategy_id,)).fetchall()
        resume = self.latest_risk_resume("max_drawdown")
        reset_ts = int(resume["approved_ts"]) if resume is not None else None
        reset_equity = (
            float(resume["baseline_equity"])
            if resume is not None and resume["baseline_equity"] is not None
            else self.initial_cash
        )
        equity = peak = reset_equity
        for row in rows:
            realized_ts = int(row["exit_ts"] or row["end_ts"])
            if reset_ts is not None and realized_ts <= reset_ts:
                continue
            pnl = float(row["pnl"])
            equity += pnl
            peak = max(peak, equity)
        if peak > 0 and (peak - equity) / peak >= max_drawdown_pct:
            return "max_drawdown"
        streak = 0
        for row in rows:
            pnl = float(row["pnl"])
            streak = streak + 1 if pnl < 0 else 0
        if streak >= max_consecutive_losses and rows:
            last_realized_ts = int(rows[-1]["exit_ts"] or rows[-1]["end_ts"])
            if now_ts < last_realized_ts + loss_streak_cooldown_seconds:
                return "loss_streak"
        offset = timezone(timedelta(hours=utc_offset_hours))
        local_day = datetime.fromtimestamp(now_ts, offset).date()
        daily_resume = self.latest_risk_resume("daily_loss")
        daily_reset_ts = (
            int(daily_resume["approved_ts"]) if daily_resume is not None else None
        )
        day_pnl = sum(
            float(row["pnl"]) for row in rows
            if datetime.fromtimestamp(int(row["end_ts"]), offset).date() == local_day
            and (
                daily_reset_ts is None
                or int(row["exit_ts"] or row["end_ts"]) > daily_reset_ts
            )
        )
        if day_pnl <= -self.initial_cash * daily_loss_pct:
            return "daily_loss"
        return None

    def settle_due(self, now_ts: int, outcome_fn: Callable[[str], str | None]) -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_positions WHERE strategy_id = ? AND end_ts <= ? "
                "AND (status = 'pending' OR "
                "(status = 'stopped' AND resolution_outcome IS NULL)) "
                "ORDER BY end_ts",
                (self.strategy_id, now_ts),
            ).fetchall()
        settled = 0
        for row in rows:
            outcome = outcome_fn(row["round_slug"])
            if outcome not in ("UP", "DOWN"):
                continue
            won = outcome == row["side"]
            hold_pnl = (float(row["shares"]) - float(row["stake"])) if won else -float(row["stake"])
            if row["status"] == "stopped":
                # already exited at the stop; only record the counterfactual so
                # false stops (resolution_outcome == side) stay measurable.
                with self._connect() as connection:
                    cursor = connection.execute("""
                        UPDATE paper_positions
                        SET resolution_outcome = ?, resolution_ts = ?, hold_pnl = ?
                        WHERE id = ? AND status = 'stopped' AND resolution_outcome IS NULL
                    """, (outcome, now_ts, hold_pnl, row["id"]))
                    settled += cursor.rowcount
                continue
            # Only the shares still held resolve here; any partially-exited shares
            # were already salvaged to exit_proceeds (a failed/partial live SELL).
            remaining = float(row["shares"]) - float(row["exited_shares"])
            payout = (remaining if won else 0.0) + float(row["exit_proceeds"])
            pnl = payout - float(row["stake"])
            status = "won" if won else "lost"
            with self._connect() as connection:
                cursor = connection.execute("""
                    UPDATE paper_positions
                    SET status = ?, outcome = ?, payout = ?, pnl = ?,
                        resolution_outcome = ?, resolution_ts = ?, hold_pnl = ?
                    WHERE id = ? AND status = 'pending'
                """, (status, outcome, payout, pnl, outcome, now_ts, hold_pnl, row["id"]))
                settled += cursor.rowcount
        return settled

    def summary(self) -> PaperSummary:
        with self._connect() as connection:
            agg = connection.execute("""
                SELECT
                    COALESCE(SUM(status IN ('pending','won','lost','stopped')), 0) AS bets,
                    COALESCE(SUM(status = 'won'), 0) AS wins,
                    COALESCE(SUM(status = 'lost'), 0) AS losses,
                    COALESCE(SUM(status = 'stopped'), 0) AS stops,
                    COALESCE(SUM(status = 'void'), 0) AS voids,
                    COALESCE(SUM(status = 'skipped'), 0) AS skips,
                    COALESCE(SUM(CASE WHEN status IN ('won','lost','stopped') THEN pnl ELSE 0 END), 0) AS pnl
                FROM paper_positions WHERE strategy_id = ?
            """, (self.strategy_id,)).fetchone()
            last = connection.execute("""
                SELECT round_slug, side, pnl FROM paper_positions
                WHERE strategy_id = ? AND status IN ('won','lost','stopped')
                ORDER BY end_ts DESC, id DESC LIMIT 1
            """, (self.strategy_id,)).fetchone()
        cash = self.current_cash()
        equity = self.current_equity()
        roi = (equity - self.initial_cash) / self.initial_cash * 100.0 if self.initial_cash else 0.0
        return PaperSummary(
            cash=cash,
            equity=equity,
            initial_cash=self.initial_cash,
            bets=int(agg["bets"]),
            wins=int(agg["wins"]),
            losses=int(agg["losses"]),
            stops=int(agg["stops"]),
            voids=int(agg["voids"]),
            skips=int(agg["skips"]),
            realized_pnl=float(agg["pnl"]),
            roi_pct=roi,
            last_round=last["round_slug"] if last else None,
            last_side=last["side"] if last else None,
            last_pnl=float(last["pnl"]) if last else None,
        )
