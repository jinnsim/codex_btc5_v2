from dataclasses import replace

from codex_btc5_v2.committee import LedgerEvidence, _update_env_text, proposed_settings
from codex_btc5_v2.config import Settings


def test_update_env_text_updates_only_review_keys():
    text = (
        "TELEGRAM_BOT_TOKEN=secret\n"
        "PAPER_MAX_BET_FRACTION=0.15\n"
        "LIVE_TRADING_ENABLED=false\n"
    )
    updated = _update_env_text(
        text,
        {
            "PAPER_MAX_BET_FRACTION": "0.03",
            "PAPER_MAX_CONSECUTIVE_LOSSES": "3",
        },
    )
    assert "TELEGRAM_BOT_TOKEN=secret" in updated
    assert "LIVE_TRADING_ENABLED=false" in updated
    assert "PAPER_MAX_BET_FRACTION=0.03" in updated
    assert "PAPER_MAX_CONSECUTIVE_LOSSES=3" in updated


def test_proposed_settings_keeps_conservative_risk_caps():
    config = replace(
        Settings(),
        paper_max_bet_fraction=0.08,
        paper_max_consecutive_losses=2,
        paper_loss_streak_cooldown_minutes=15,
    )
    proposed = proposed_settings(
        config,
        LedgerEvidence(decided=30, wins=12, losses=18, stake=100.0, pnl=-8.0),
    )
    assert proposed["PAPER_MAX_BET_FRACTION"] == "0.03"
    assert proposed["PAPER_MAX_CONSECUTIVE_LOSSES"] == "3"
    assert proposed["PAPER_LOSS_STREAK_COOLDOWN_MINUTES"] == "60"
