from codex_btc5_v2.config import Settings
from codex_btc5_v2.indicators import IndicatorSnapshot, momentum_direction, momentum_interpretation


def snap(ret, hist, rsi):
    return IndicatorSnapshot(symbol="BTCUSDT", price=100.0, return_5m_pct=ret, rsi_14=rsi,
                             macd=1.0, macd_signal=0.0, macd_histogram=hist, candle_close_ts=0)


def test_small_positive_return_within_deadband_is_mixed():
    # hist>0 and rsi>50 are bullish, but +0.014% return is inside ±0.02% -> not 3/3
    assert momentum_direction(snap(0.014, 1.5, 52.0), deadband_pct=0.02) == "MIXED"


def test_same_snapshot_is_rising_with_zero_deadband():
    assert momentum_direction(snap(0.014, 1.5, 52.0), deadband_pct=0.0) == "RISING"


def test_return_above_deadband_is_rising():
    assert momentum_direction(snap(0.05, 1.5, 52.0), deadband_pct=0.02) == "RISING"


def test_small_negative_return_within_deadband_is_mixed():
    assert momentum_direction(snap(-0.014, -1.5, 48.0), deadband_pct=0.02) == "MIXED"


def test_return_below_deadband_is_falling():
    assert momentum_direction(snap(-0.05, -1.5, 48.0), deadband_pct=0.02) == "FALLING"


def test_default_deadband_comes_from_settings():
    # Handoff tuning uses 0.045 -> +0.014% is neutralized without an explicit arg.
    assert Settings().momentum_return_deadband_pct == 0.045
    assert momentum_direction(snap(0.014, 1.5, 52.0)) == "MIXED"


def test_interpretation_reports_deadband_adjusted_counts():
    txt = momentum_interpretation(snap(0.014, 1.5, 52.0), deadband_pct=0.02)
    assert "혼조" in txt
    assert "상승 조건 2/3" in txt
    assert "하락 조건 0/3" in txt
