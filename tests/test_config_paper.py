from dataclasses import replace
import pytest
from codex_btc5_v2.config import Settings


def test_paper_defaults():
    s = Settings()
    assert s.paper_trading_enabled is True
    assert s.paper_initial_cash == 145.0
    assert s.paper_bet_fraction == 0.25
    assert s.paper_min_bet_fraction == 0.01
    assert s.paper_max_bet_fraction == 0.03
    assert s.paper_stop_loss_pct == 0.20
    assert s.paper_stop_loss_enabled is True
    assert s.paper_stop_confirmations == 2
    assert s.paper_max_drawdown_pct == 0.10
    assert s.paper_daily_loss_pct == 0.08
    assert s.paper_max_consecutive_losses == 3
    assert s.paper_loss_streak_cooldown_minutes == 60
    assert s.paper_ledger_db == "data/paper_ledger.sqlite3"
    assert s.paper_strategy_id == "trend-v2-5m"
    assert s.gamma_base_url == "https://gamma-api.polymarket.com"
    assert s.clob_base_url == "https://clob.polymarket.com"


def test_validate_paper_rejects_bad_fraction():
    with pytest.raises(ValueError):
        replace(Settings(), paper_bet_fraction=0.0).validate_paper()
    with pytest.raises(ValueError):
        replace(Settings(), paper_bet_fraction=1.5).validate_paper()


def test_validate_paper_rejects_nonpositive_cash():
    with pytest.raises(ValueError):
        replace(Settings(), paper_initial_cash=0.0).validate_paper()


def test_validate_paper_accepts_good_values():
    replace(Settings(), paper_bet_fraction=0.25, paper_initial_cash=100.0).validate_paper()


def test_validate_paper_rejects_bad_dynamic_range():
    with pytest.raises(ValueError):
        replace(Settings(), paper_min_bet_fraction=0.30,
                paper_max_bet_fraction=0.25).validate_paper()


def test_validate_paper_rejects_invalid_stop_loss():
    with pytest.raises(ValueError):
        replace(Settings(), paper_stop_loss_pct=0.0).validate_paper()
    with pytest.raises(ValueError):
        replace(Settings(), paper_stop_loss_pct=1.0).validate_paper()
