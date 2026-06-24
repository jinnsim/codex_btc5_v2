import pytest

from codex_btc5_v2.config import Settings
from codex_btc5_v2.indicators import (
    calculate, fetch_snapshot, format_snapshot, momentum_direction,
    momentum_interpretation,
)


def test_calculates_indicators():
    closes = [100.0] * 40 + [101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    snapshot = calculate(closes, 123, "BTCUSDT")
    assert snapshot.price == 106.0
    assert snapshot.return_5m_pct == pytest.approx((106.0 / 101.0 - 1.0) * 100.0)
    assert snapshot.rsi_14 == 100.0
    assert snapshot.macd_histogram > 0
    assert momentum_interpretation(snapshot) == "상승 모멘텀 관측 (3/3 지표 정렬)"
    assert momentum_direction(snapshot) == "RISING"


def test_message_has_no_recommendation():
    snapshot = calculate(list(map(float, range(100, 150))), 123, "BTCUSDT")
    text = format_snapshot(snapshot)
    assert "RSI(14)" in text
    assert "MACD(12,26,9)" in text
    assert "해석: 상승 모멘텀 관측" in text
    assert "no UP/DOWN recommendation" in text


def test_fetch_snapshot_excludes_open_candle(monkeypatch):
    now_ms = 2_000_000
    closed = [[0, 0, 0, 0, str(100 + i), 0, now_ms - 1000 - i] for i in range(40)]
    closed.sort(key=lambda row: row[6])
    open_candle = [0, 0, 0, 0, "999", 0, now_ms + 59_000]

    class Response:
        def raise_for_status(self): pass
        def json(self): return closed + [open_candle]

    class Session:
        def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr("codex_btc5_v2.indicators.time.time", lambda: now_ms / 1000)
    snapshot = fetch_snapshot(Settings(), Session())
    assert snapshot.price != 999.0
    assert snapshot.candle_close_ts <= now_ms // 1000
