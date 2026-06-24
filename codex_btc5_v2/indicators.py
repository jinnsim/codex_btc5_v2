from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time

import requests

from .config import Settings, settings


@dataclass(frozen=True)
class IndicatorSnapshot:
    symbol: str
    price: float
    return_5m_pct: float
    rsi_14: float
    macd: float
    macd_signal: float
    macd_histogram: float
    candle_close_ts: int


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"need at least {period} values")
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        raise ValueError(f"need more than {period} values")
    changes = [current - previous for previous, current in zip(values, values[1:])]
    avg_gain = sum(max(change, 0.0) for change in changes[:period]) / period
    avg_loss = sum(max(-change, 0.0) for change in changes[:period]) / period
    for change in changes[period:]:
        avg_gain = ((period - 1) * avg_gain + max(change, 0.0)) / period
        avg_loss = ((period - 1) * avg_loss + max(-change, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def calculate(closes: list[float], candle_close_ts: int, symbol: str) -> IndicatorSnapshot:
    if len(closes) < 35:
        raise ValueError("need at least 35 closing prices")
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    macd_series = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal_series = ema(macd_series, 9)
    macd_value = macd_series[-1]
    signal_value = signal_series[-1]
    return IndicatorSnapshot(
        symbol=symbol,
        price=closes[-1],
        return_5m_pct=(closes[-1] / closes[-6] - 1.0) * 100.0,
        rsi_14=rsi(closes),
        macd=macd_value,
        macd_signal=signal_value,
        macd_histogram=macd_value - signal_value,
        candle_close_ts=candle_close_ts,
    )


def fetch_snapshot(config: Settings = settings, session=requests,
                   now_ts: float | None = None) -> IndicatorSnapshot:
    response = session.get(
        f"{config.binance_base_url}/api/v3/klines",
        params={"symbol": config.btc_symbol, "interval": "1m", "limit": 100},
        timeout=config.http_timeout,
    )
    response.raise_for_status()
    rows = response.json()
    if len(rows) < 35:
        raise RuntimeError("Binance returned too few candles")
    now_ms = int((time.time() if now_ts is None else now_ts) * 1000)
    closed_rows = [row for row in rows if int(row[6]) < now_ms]
    if len(closed_rows) < 35:
        raise RuntimeError("Binance returned too few completed candles")
    closes = [float(row[4]) for row in closed_rows]
    return calculate(closes, int(closed_rows[-1][6]) // 1000, config.btc_symbol)


def _alignment(snapshot: IndicatorSnapshot, deadband_pct: float) -> tuple[int, int]:
    """Count bullish/bearish conditions. The 5m return must clear ±deadband_pct
    (a neutral band around 0) to count; RSI/MACD use their natural 50/0 pivots."""
    positive = sum((
        snapshot.return_5m_pct > deadband_pct,
        snapshot.macd_histogram > 0,
        snapshot.rsi_14 > 50,
    ))
    negative = sum((
        snapshot.return_5m_pct < -deadband_pct,
        snapshot.macd_histogram < 0,
        snapshot.rsi_14 < 50,
    ))
    return positive, negative


def momentum_direction(snapshot: IndicatorSnapshot, deadband_pct: float | None = None) -> str:
    """Classify alignment for paper evaluation; MIXED is not scored."""
    threshold = settings.momentum_return_deadband_pct if deadband_pct is None else deadband_pct
    positive, negative = _alignment(snapshot, threshold)
    if positive == 3:
        return "RISING"
    if negative == 3:
        return "FALLING"
    return "MIXED"


def momentum_interpretation(snapshot: IndicatorSnapshot, deadband_pct: float | None = None) -> str:
    threshold = settings.momentum_return_deadband_pct if deadband_pct is None else deadband_pct
    direction = momentum_direction(snapshot, threshold)
    if direction == "RISING":
        return "상승 모멘텀 관측 (3/3 지표 정렬)"
    if direction == "FALLING":
        return "하락 모멘텀 관측 (3/3 지표 정렬)"
    positive, negative = _alignment(snapshot, threshold)
    return f"혼조 (상승 조건 {positive}/3, 하락 조건 {negative}/3)"


def format_snapshot(snapshot: IndicatorSnapshot) -> str:
    if snapshot.rsi_14 >= 70:
        rsi_zone = "above_70"
    elif snapshot.rsi_14 <= 30:
        rsi_zone = "below_30"
    else:
        rsi_zone = "30_to_70"
    relation = "above_signal" if snapshot.macd >= snapshot.macd_signal else "below_signal"
    close_time = datetime.fromtimestamp(snapshot.candle_close_ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    interpretation = momentum_interpretation(snapshot)
    return (
        f"📊 {snapshot.symbol} 1m indicators\n"
        f"🧭 해석: {interpretation}\n"
        f"price {snapshot.price:,.2f} | 5m return {snapshot.return_5m_pct:+.3f}%\n"
        f"RSI(14) {snapshot.rsi_14:.2f} [{rsi_zone}]\n"
        f"MACD(12,26,9) {snapshot.macd:+.2f} | signal {snapshot.macd_signal:+.2f} "
        f"| hist {snapshot.macd_histogram:+.2f} [{relation}]\n"
        f"candle close {close_time}\n"
        "measurement only; no UP/DOWN recommendation"
    )


def indicator_text(config: Settings = settings, session=requests) -> str:
    return format_snapshot(fetch_snapshot(config, session))
