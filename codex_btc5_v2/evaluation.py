from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator

import requests

from .config import Settings, settings
from .indicators import IndicatorSnapshot, momentum_direction


@dataclass(frozen=True)
class AccuracySummary:
    pending: int
    excluded: int
    resolved: int
    hits: int
    rising_resolved: int
    rising_hits: int
    falling_resolved: int
    falling_hits: int


class EvaluationStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    source_close_ts INTEGER NOT NULL,
                    target_close_ts INTEGER NOT NULL,
                    source_price REAL NOT NULL,
                    direction TEXT NOT NULL,
                    rsi_14 REAL NOT NULL,
                    macd_histogram REAL NOT NULL,
                    return_5m_pct REAL NOT NULL,
                    status TEXT NOT NULL,
                    actual_close_ts INTEGER,
                    actual_price REAL,
                    actual_direction TEXT,
                    hit INTEGER,
                    UNIQUE(symbol, source_close_ts)
                )
            """)

    def record(self, snapshot: IndicatorSnapshot) -> bool:
        direction = momentum_direction(snapshot)
        status = "excluded" if direction == "MIXED" else "pending"
        with self._connect() as connection:
            cursor = connection.execute("""
                INSERT OR IGNORE INTO evaluations (
                    symbol, source_close_ts, target_close_ts, source_price,
                    direction, rsi_14, macd_histogram, return_5m_pct, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.symbol,
                snapshot.candle_close_ts,
                snapshot.candle_close_ts + 300,
                snapshot.price,
                direction,
                snapshot.rsi_14,
                snapshot.macd_histogram,
                snapshot.return_5m_pct,
                status,
            ))
            return cursor.rowcount == 1

    def _target_close(self, config: Settings, target_close_ts: int, session=requests) -> tuple[int, float] | None:
        response = session.get(
            f"{config.binance_base_url}/api/v3/klines",
            params={
                "symbol": config.btc_symbol,
                "interval": "1m",
                "endTime": target_close_ts * 1000 + 999,
                "limit": 1,
            },
            timeout=config.http_timeout,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None
        close_ts = int(rows[-1][6]) // 1000
        if close_ts != target_close_ts:
            return None
        return close_ts, float(rows[-1][4])

    def resolve_due(self, now_close_ts: int, config: Settings = settings, session=requests) -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evaluations WHERE status = 'pending' AND target_close_ts <= ? ORDER BY target_close_ts",
                (now_close_ts,),
            ).fetchall()
        resolved = 0
        for row in rows:
            target = self._target_close(config, row["target_close_ts"], session)
            if target is None:
                continue
            actual_close_ts, actual_price = target
            if actual_price > row["source_price"]:
                actual_direction = "RISING"
            elif actual_price < row["source_price"]:
                actual_direction = "FALLING"
            else:
                actual_direction = "FLAT"
            hit = int(actual_direction == row["direction"])
            with self._connect() as connection:
                cursor = connection.execute("""
                    UPDATE evaluations
                    SET status = 'resolved', actual_close_ts = ?, actual_price = ?,
                        actual_direction = ?, hit = ?
                    WHERE id = ? AND status = 'pending'
                """, (actual_close_ts, actual_price, actual_direction, hit, row["id"]))
                resolved += cursor.rowcount
        return resolved

    def summary(self) -> AccuracySummary:
        with self._connect() as connection:
            row = connection.execute("""
                SELECT
                    SUM(status = 'pending') AS pending,
                    SUM(status = 'excluded') AS excluded,
                    SUM(status = 'resolved') AS resolved,
                    SUM(CASE WHEN status = 'resolved' THEN hit ELSE 0 END) AS hits,
                    SUM(status = 'resolved' AND direction = 'RISING') AS rising_resolved,
                    SUM(CASE WHEN status = 'resolved' AND direction = 'RISING' THEN hit ELSE 0 END) AS rising_hits,
                    SUM(status = 'resolved' AND direction = 'FALLING') AS falling_resolved,
                    SUM(CASE WHEN status = 'resolved' AND direction = 'FALLING' THEN hit ELSE 0 END) AS falling_hits
                FROM evaluations
            """).fetchone()
        return AccuracySummary(*(int(value or 0) for value in row))


def _rate(hits: int, total: int) -> str:
    return "n/a" if total == 0 else f"{hits / total * 100:.1f}%"


def format_accuracy(summary: AccuracySummary) -> str:
    return (
        "🧪 5분 후 방향 페이퍼 평가\n"
        f"전체 {_rate(summary.hits, summary.resolved)} "
        f"({summary.hits}/{summary.resolved})\n"
        f"상승 모멘텀 {_rate(summary.rising_hits, summary.rising_resolved)} "
        f"({summary.rising_hits}/{summary.rising_resolved})\n"
        f"하락 모멘텀 {_rate(summary.falling_hits, summary.falling_resolved)} "
        f"({summary.falling_hits}/{summary.falling_resolved})\n"
        f"판정 대기 {summary.pending} | 혼조 제외 {summary.excluded}\n"
        "과거 측정 결과이며 다음 결과를 보장하지 않음"
    )
