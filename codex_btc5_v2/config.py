from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    btc_symbol: str = os.getenv("BTC_SYMBOL", "BTCUSDT")
    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/")
    telegram_enabled: bool = _bool("TELEGRAM_ENABLED")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    indicator_digest_interval: float = float(os.getenv("INDICATOR_DIGEST_INTERVAL", "0"))
    indicator_schedule_minutes: int = int(os.getenv("INDICATOR_SCHEDULE_MINUTES", "0"))
    telegram_poll_interval: float = float(os.getenv("TELEGRAM_POLL_INTERVAL", "2"))
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "10"))
    evaluation_db: str = os.getenv("EVALUATION_DB", "data/evaluations.sqlite3")
    paper_trading_enabled: bool = _bool("PAPER_TRADING_ENABLED")
    paper_initial_cash: float = float(os.getenv("PAPER_INITIAL_CASH", "100"))
    paper_bet_fraction: float = float(os.getenv("PAPER_BET_FRACTION", "0.25"))
    paper_min_bet_fraction: float = float(os.getenv("PAPER_MIN_BET_FRACTION", "0.02"))
    paper_max_bet_fraction: float = float(os.getenv("PAPER_MAX_BET_FRACTION", "0.15"))
    paper_ledger_db: str = os.getenv("PAPER_LEDGER_DB", "data/paper_ledger.sqlite3")
    paper_strategy_id: str = os.getenv("PAPER_STRATEGY_ID", "trend-v2")
    paper_risk_shadow_enabled: bool = _bool("PAPER_RISK_SHADOW_ENABLED")
    paper_stop_loss_enabled: bool = _bool("PAPER_STOP_LOSS_ENABLED")
    paper_stop_loss_pct: float = float(os.getenv("PAPER_STOP_LOSS_PCT", "0.20"))
    paper_stop_confirmations: int = int(os.getenv("PAPER_STOP_CONFIRMATIONS", "3"))
    paper_stop_confirmation_seconds: int = int(os.getenv("PAPER_STOP_CONFIRMATION_SECONDS", "30"))
    paper_max_drawdown_pct: float = float(os.getenv("PAPER_MAX_DRAWDOWN_PCT", "0.10"))
    paper_daily_loss_pct: float = float(os.getenv("PAPER_DAILY_LOSS_PCT", "0.08"))
    paper_max_consecutive_losses: int = int(os.getenv("PAPER_MAX_CONSECUTIVE_LOSSES", "3"))
    paper_loss_streak_cooldown_minutes: int = int(
        os.getenv("PAPER_LOSS_STREAK_COOLDOWN_MINUTES", "60")
    )
    paper_session_utc_offset_hours: int = int(os.getenv("PAPER_SESSION_UTC_OFFSET_HOURS", "9"))
    gamma_base_url: str = os.getenv("GAMMA_BASE_URL", "https://gamma-api.polymarket.com").rstrip("/")
    clob_base_url: str = os.getenv("CLOB_BASE_URL", "https://clob.polymarket.com").rstrip("/")
    # Neutral band (in %) around 0 for the 5m-return momentum condition. A return
    # within ±deadband counts as neither bullish nor bearish (filters noise).
    momentum_return_deadband_pct: float = float(os.getenv("MOMENTUM_RETURN_DEADBAND_PCT", "0.02"))

    # ---- LIVE trading (REAL money). Two independent safety gates: ----
    # live_trading_enabled = master kill switch (default OFF).
    # live_dry_run = even when enabled, simulate fills without submitting (default ON).
    # Real orders fire ONLY when live_trading_enabled=true AND live_dry_run=false.
    live_trading_enabled: bool = _bool("LIVE_TRADING_ENABLED")
    live_dry_run: bool = _bool("LIVE_DRY_RUN", "true")
    poly_private_key: str = os.getenv("POLY_PRIVATE_KEY", "")
    # 0 = EOA (key holds USDC). 1 = email/magic proxy. 2 = browser/metamask proxy.
    poly_signature_type: int = int(os.getenv("POLY_SIGNATURE_TYPE", "0"))
    # Proxy wallet that holds USDC (signature_type 1/2). Empty = use the key's own address.
    poly_funder: str = os.getenv("POLY_FUNDER", "")
    poly_chain_id: int = int(os.getenv("POLY_CHAIN_ID", "137"))
    live_order_type: str = os.getenv("LIVE_ORDER_TYPE", "FAK")  # immediate-or-cancel
    live_ledger_db: str = os.getenv("LIVE_LEDGER_DB", "data/live_fills.sqlite3")

    def validate_no_live(self) -> None:
        if self.live_trading_enabled:
            raise ValueError("codex_btc5_v2 is paper-only; LIVE_TRADING_ENABLED must stay false")
        if not self.live_dry_run:
            raise ValueError("codex_btc5_v2 is paper-only; LIVE_DRY_RUN must stay true")

    def validate_live(self) -> None:
        self.validate_no_live()

    def validate_telegram(self) -> None:
        if self.telegram_enabled and (not self.telegram_bot_token or not self.telegram_chat_id):
            raise ValueError("TELEGRAM_ENABLED requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        if self.indicator_schedule_minutes < 0 or self.indicator_schedule_minutes > 60:
            raise ValueError("INDICATOR_SCHEDULE_MINUTES must be 0..60")

    def validate_paper(self) -> None:
        if not (0.0 < self.paper_bet_fraction <= 1.0):
            raise ValueError("PAPER_BET_FRACTION must be in (0, 1]")
        if not (0.0 < self.paper_min_bet_fraction <= self.paper_max_bet_fraction <= 1.0):
            raise ValueError("paper bet fractions must satisfy 0 < min <= max <= 1")
        if self.paper_initial_cash <= 0:
            raise ValueError("PAPER_INITIAL_CASH must be > 0")
        if not (0.0 < self.paper_stop_loss_pct < 1.0):
            raise ValueError("PAPER_STOP_LOSS_PCT must be in (0, 1)")
        if not self.paper_strategy_id.strip():
            raise ValueError("PAPER_STRATEGY_ID must not be empty")
        if self.paper_stop_confirmations < 1 or self.paper_stop_confirmation_seconds < 0:
            raise ValueError("paper stop confirmation settings are invalid")
        if not (0.0 < self.paper_max_drawdown_pct < 1.0):
            raise ValueError("PAPER_MAX_DRAWDOWN_PCT must be in (0, 1)")
        if not (0.0 < self.paper_daily_loss_pct < 1.0):
            raise ValueError("PAPER_DAILY_LOSS_PCT must be in (0, 1)")
        if self.paper_max_consecutive_losses < 1:
            raise ValueError("PAPER_MAX_CONSECUTIVE_LOSSES must be >= 1")
        if self.paper_loss_streak_cooldown_minutes < 1:
            raise ValueError("PAPER_LOSS_STREAK_COOLDOWN_MINUTES must be >= 1")
        if not (-23 <= self.paper_session_utc_offset_hours <= 23):
            raise ValueError("PAPER_SESSION_UTC_OFFSET_HOURS must be -23..23")


settings = Settings()
