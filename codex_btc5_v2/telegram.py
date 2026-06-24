from __future__ import annotations

import json
import time

import requests

from .config import Settings, settings
from .indicators import indicator_text
from .evaluation import EvaluationStore, format_accuracy
from .paper import PaperBook
from .committee import apply_committee_review, build_committee_review

HELP = (
    "commands: /indicators /accuracy /paper /status /resume "
    "/committee_review /apply_review /help"
)

# Native Telegram command menu (registered via setMyCommands). Measurement only.
BOT_COMMANDS = (
    ("indicators", "RSI/MACD/5m 수익률 현재 측정"),
    ("accuracy", "5분 후 방향 페이퍼 적중률"),
    ("paper", "현재 뱅크롤 및 실현 손익"),
    ("status", "봇 상태/모드"),
    ("resume", "max_drawdown 승인 후 거래 재개"),
    ("committee_review", "누적 근거 기반 위원회 리뷰 요청"),
    ("apply_review", "위원회 권고 승인 적용 후 재구동"),
    ("help", "명령 목록"),
)


class TelegramClient:
    def __init__(self, config: Settings = settings, session=requests):
        self.config = config
        self.session = session
        self.restart_requested = False

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.config.telegram_bot_token}/{method}"

    def send(self, text: str) -> bool:
        if not self.config.telegram_enabled:
            return False
        chunks = [text[i:i + 3500] for i in range(0, len(text), 3500)] or [""]
        for chunk in chunks:
            response = self.session.post(
                self._url("sendMessage"),
                data={"chat_id": self.config.telegram_chat_id, "text": chunk},
                timeout=self.config.http_timeout,
            )
            response.raise_for_status()
        return True

    def set_commands(self) -> bool:
        """Register the native command menu via setMyCommands. Read-only menu."""
        if not self.config.telegram_enabled:
            return False
        commands = [{"command": name, "description": desc} for name, desc in BOT_COMMANDS]
        response = self.session.post(
            self._url("setMyCommands"),
            data={"commands": json.dumps(commands)},
            timeout=self.config.http_timeout,
        )
        response.raise_for_status()
        return True

    def command_response(self, text: str | None) -> str | None:
        if not text:
            return None
        command = text.strip().split()[0].lstrip("/").split("@")[0].lower()
        if command == "indicators":
            return indicator_text(self.config, self.session)
        if command == "accuracy":
            return format_accuracy(EvaluationStore(self.config.evaluation_db).summary())
        if command == "paper":
            from .runner import format_paper
            strategy_id = self.config.paper_strategy_id
            initial_cash = PaperBook.persisted_initial_cash(
                self.config.paper_ledger_db, strategy_id
            )
            if initial_cash is None:
                initial_cash = self.config.paper_initial_cash
            book = PaperBook(
                self.config.paper_ledger_db, initial_cash, strategy_id
            )
            return format_paper(book.summary(), self.config)
        if command in {"resume", "approve"}:
            strategy_id = self.config.paper_strategy_id
            initial_cash = PaperBook.persisted_initial_cash(
                self.config.paper_ledger_db, strategy_id
            )
            if initial_cash is None:
                initial_cash = self.config.paper_initial_cash
            book = PaperBook(self.config.paper_ledger_db, initial_cash, strategy_id)
            approved_ts = int(time.time())
            baseline = book.approve_risk_resume("max_drawdown", approved_ts)
            book.approve_risk_resume("daily_loss", approved_ts)
            return (
                "✅ 리스크 재개 승인 완료 (max_drawdown + daily_loss)\n"
                f"새 drawdown 기준 equity: {baseline:,.2f} pUSD\n"
                "다음 5분 라운드부터 조건 충족 시 거래 재개"
            )
        if command in {"committee_review", "commite_review"}:
            return build_committee_review(self.config)
        if command in {"apply_review", "approve_review"}:
            reply = apply_committee_review()
            self.restart_requested = reply.startswith("✅")
            return reply
        if command == "status":
            if self.config.indicator_schedule_minutes > 0:
                mode = f"wall-clock every {self.config.indicator_schedule_minutes}m"
            else:
                digest = self.config.indicator_digest_interval
                mode = "command-only" if digest <= 0 else f"automatic every {digest:g}s"
            return f"🟢 codex_btc5_v2 running | {self.config.btc_symbol} | {mode}"
        if command in {"start", "help"}:
            return HELP
        return None

    def poll_once(self, offset: int) -> int:
        response = self.session.get(
            self._url("getUpdates"),
            params={"offset": offset, "timeout": 0},
            timeout=self.config.http_timeout,
        )
        response.raise_for_status()
        next_offset = offset
        for update in response.json().get("result", []):
            next_offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat_id = str(message.get("chat", {}).get("id", ""))
            if chat_id != str(self.config.telegram_chat_id):
                continue
            reply = self.command_response(message.get("text"))
            if reply:
                self.send(reply)
            if self.restart_requested:
                raise SystemExit(0)
        return next_offset
