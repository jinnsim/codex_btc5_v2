from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
import subprocess
import time

from .config import Settings, settings


REVIEW_PROPOSAL_PATH = Path("data/committee_proposal.json")
REVIEW_EVIDENCE_PATH = Path("data/committee_evidence.json")
REVIEW_SCHEMA_PATH = Path("data/committee_schema.json")
REVIEW_CODEX_OUTPUT_PATH = Path("data/committee_codex_response.json")
APPLY_KEYS = (
    "PAPER_MAX_BET_FRACTION",
    "PAPER_MAX_CONSECUTIVE_LOSSES",
    "PAPER_LOSS_STREAK_COOLDOWN_MINUTES",
    "PAPER_MAX_DRAWDOWN_PCT",
    "PAPER_DAILY_LOSS_PCT",
)
CODEX_TIMEOUT_SECONDS = 240


@dataclass(frozen=True)
class LedgerEvidence:
    decided: int = 0
    wins: int = 0
    losses: int = 0
    stops: int = 0
    skips: int = 0
    stake: float = 0.0
    pnl: float = 0.0
    pending: int = 0
    mixed: int = 0
    risk_skips: int = 0
    no_market: int = 0
    live_fills: int = 0
    live_errors: int = 0
    live_usdc: float = 0.0
    wallet_usdc: float | None = None
    positions_value: float | None = None

    @property
    def win_rate(self) -> float:
        return 0.0 if self.decided == 0 else self.wins / self.decided * 100.0

    @property
    def roi_on_stake(self) -> float:
        return 0.0 if self.stake <= 0 else self.pnl / self.stake * 100.0


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _paper_evidence(config: Settings) -> LedgerEvidence:
    path = Path(config.paper_ledger_db)
    if not path.exists():
        return LedgerEvidence()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "paper_positions"):
            return LedgerEvidence()
        row = connection.execute(
            """
            SELECT
                SUM(status IN ('won','lost','stopped')) AS decided,
                SUM(status='won') AS wins,
                SUM(status='lost') AS losses,
                SUM(status='stopped') AS stops,
                SUM(status='skipped') AS skips,
                SUM(status='pending') AS pending,
                SUM(CASE WHEN status IN ('won','lost','stopped')
                    THEN COALESCE(stake,0) ELSE 0 END) AS stake,
                SUM(CASE WHEN status IN ('won','lost','stopped')
                    THEN COALESCE(pnl,0) ELSE 0 END) AS pnl,
                SUM(status='skipped' AND outcome='mixed') AS mixed,
                SUM(status='skipped' AND outcome LIKE 'risk-%') AS risk_skips,
                SUM(status='skipped' AND outcome='no_market') AS no_market
            FROM paper_positions
            WHERE strategy_id = ?
            """,
            (config.paper_strategy_id,),
        ).fetchone()
    return LedgerEvidence(
        decided=int(row["decided"] or 0),
        wins=int(row["wins"] or 0),
        losses=int(row["losses"] or 0),
        stops=int(row["stops"] or 0),
        skips=int(row["skips"] or 0),
        stake=float(row["stake"] or 0.0),
        pnl=float(row["pnl"] or 0.0),
        pending=int(row["pending"] or 0),
        mixed=int(row["mixed"] or 0),
        risk_skips=int(row["risk_skips"] or 0),
        no_market=int(row["no_market"] or 0),
    )


def _live_evidence(config: Settings, evidence: LedgerEvidence) -> LedgerEvidence:
    path = Path(config.live_ledger_db)
    if not path.exists():
        return evidence
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        fills = {"live_fills": 0, "live_errors": 0, "live_usdc": 0.0}
        wallet = None
        positions_value = None
        if _table_exists(connection, "live_fills"):
            row = connection.execute(
                """
                SELECT
                    SUM(status IN ('filled','dry_fill')) AS live_fills,
                    SUM(status NOT IN ('filled','dry_fill')) AS live_errors,
                    SUM(CASE WHEN status IN ('filled','dry_fill')
                        THEN COALESCE(filled_usdc,0) ELSE 0 END) AS live_usdc
                FROM live_fills
                """
            ).fetchone()
            fills = {
                "live_fills": int(row["live_fills"] or 0),
                "live_errors": int(row["live_errors"] or 0),
                "live_usdc": float(row["live_usdc"] or 0.0),
            }
        if _table_exists(connection, "live_account"):
            row = connection.execute(
                "SELECT wallet_usdc, positions_value FROM live_account ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                wallet = None if row["wallet_usdc"] is None else float(row["wallet_usdc"])
                positions_value = (
                    None if row["positions_value"] is None else float(row["positions_value"])
                )
    return LedgerEvidence(
        **{**evidence.__dict__, **fills,
           "wallet_usdc": wallet, "positions_value": positions_value}
    )


def collect_evidence(config: Settings = settings) -> LedgerEvidence:
    evidence = _paper_evidence(config)
    if config.live_trading_enabled:
        evidence = _live_evidence(config, evidence)
    return evidence


def _recent_paper_rows(config: Settings, limit: int = 40) -> list[dict]:
    path = Path(config.paper_ledger_db)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "paper_positions"):
            return []
        rows = connection.execute(
            """
            SELECT datetime(boundary_ts,'unixepoch','+9 hours') AS kst,
                   side, stake, status, outcome, pnl, round_slug
            FROM paper_positions
            WHERE strategy_id = ?
            ORDER BY boundary_ts DESC
            LIMIT ?
            """,
            (config.paper_strategy_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _recent_live_rows(config: Settings, limit: int = 40) -> list[dict]:
    path = Path(config.live_ledger_db)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "live_fills"):
            return []
        rows = connection.execute(
            """
            SELECT datetime(ts,'unixepoch','+9 hours') AS kst,
                   kind, side, ref_price, req_usdc, req_shares,
                   filled_shares, filled_usdc, avg_price, status
            FROM live_fills
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _write_codex_schema() -> None:
    REVIEW_SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_SCHEMA_PATH.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["report", "settings"],
                "properties": {
                    "report": {"type": "string"},
                    "settings": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(APPLY_KEYS),
                        "properties": {key: {"type": "string"} for key in APPLY_KEYS},
                    },
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def build_evidence_snapshot(config: Settings = settings) -> dict:
    evidence = collect_evidence(config)
    current = _current_settings(config)
    return {
        "bot": config.paper_strategy_id,
        "mode": "LIVE" if config.live_trading_enabled and not config.live_dry_run else "PAPER",
        "generated_at": int(time.time()),
        "current_settings": current,
        "allowed_setting_keys": list(APPLY_KEYS),
        "ledger_summary": evidence.__dict__,
        "paper_ledger_db": config.paper_ledger_db,
        "live_ledger_db": config.live_ledger_db if config.live_trading_enabled else None,
        "recent_paper_rows": _recent_paper_rows(config),
        "recent_live_fills": _recent_live_rows(config) if config.live_trading_enabled else [],
        "fallback_rule_proposal": proposed_settings(config, evidence),
    }


def _validate_settings(raw: dict, fallback: dict[str, str]) -> dict[str, str]:
    settings_out: dict[str, str] = {}
    for key in APPLY_KEYS:
        settings_out[key] = str(raw.get(key, fallback[key])).strip()
    max_bet = float(settings_out["PAPER_MAX_BET_FRACTION"])
    max_losses = int(settings_out["PAPER_MAX_CONSECUTIVE_LOSSES"])
    cooldown = int(settings_out["PAPER_LOSS_STREAK_COOLDOWN_MINUTES"])
    max_drawdown = float(settings_out["PAPER_MAX_DRAWDOWN_PCT"])
    daily_loss = float(settings_out["PAPER_DAILY_LOSS_PCT"])
    if not (0.005 <= max_bet <= 0.10):
        raise ValueError("PAPER_MAX_BET_FRACTION must be 0.005..0.10")
    if not (1 <= max_losses <= 10):
        raise ValueError("PAPER_MAX_CONSECUTIVE_LOSSES must be 1..10")
    if not (5 <= cooldown <= 360):
        raise ValueError("PAPER_LOSS_STREAK_COOLDOWN_MINUTES must be 5..360")
    if not (0.01 <= max_drawdown <= 0.50):
        raise ValueError("PAPER_MAX_DRAWDOWN_PCT must be 0.01..0.50")
    if not (0.01 <= daily_loss <= 0.50):
        raise ValueError("PAPER_DAILY_LOSS_PCT must be 0.01..0.50")
    return {
        "PAPER_MAX_BET_FRACTION": f"{max_bet:.3g}",
        "PAPER_MAX_CONSECUTIVE_LOSSES": str(max_losses),
        "PAPER_LOSS_STREAK_COOLDOWN_MINUTES": str(cooldown),
        "PAPER_MAX_DRAWDOWN_PCT": f"{max_drawdown:.3g}",
        "PAPER_DAILY_LOSS_PCT": f"{daily_loss:.3g}",
    }


def _run_codex_committee(snapshot: dict) -> dict:
    REVIEW_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_EVIDENCE_PATH.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_codex_schema()
    prompt = (
        "너는 Polymarket BTC 5분 봇 운영 위원회다. "
        "첨부 근거 JSON 파일만 근거로 최근 거래/스킵/실체결 품질을 리뷰하고, "
        "리스크 설정을 유지/조정할지 판단하라.\n\n"
        f"근거 파일: {REVIEW_EVIDENCE_PATH.resolve()}\n"
        "반드시 한국어로 간결하게 report를 작성한다. report에는 근거 수치를 포함한다. "
        "settings에는 allowed_setting_keys 다섯 개만 넣는다. "
        "근거가 부족하면 보수적으로 fallback_rule_proposal을 따른다. "
        "비밀키, 토큰, 환경변수 원문은 절대 출력하지 않는다."
    )
    result = subprocess.run(
        [
            "codex",
            "exec",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(REVIEW_SCHEMA_PATH),
            "--output-last-message",
            str(REVIEW_CODEX_OUTPUT_PATH),
            prompt,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=CODEX_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "codex exec failed").strip())
    if not REVIEW_CODEX_OUTPUT_PATH.exists():
        raise RuntimeError("codex exec did not write committee response")
    return json.loads(REVIEW_CODEX_OUTPUT_PATH.read_text(encoding="utf-8"))


def proposed_settings(config: Settings, evidence: LedgerEvidence) -> dict[str, str]:
    max_bet = min(config.paper_max_bet_fraction, 0.03)
    cooldown = max(config.paper_loss_streak_cooldown_minutes, 60)
    max_losses = max(config.paper_max_consecutive_losses, 3)
    if evidence.decided >= 20 and evidence.pnl > 0 and evidence.win_rate >= 55.0:
        max_bet = config.paper_max_bet_fraction
    return {
        "PAPER_MAX_BET_FRACTION": f"{max_bet:.2f}",
        "PAPER_MAX_CONSECUTIVE_LOSSES": str(max_losses),
        "PAPER_LOSS_STREAK_COOLDOWN_MINUTES": str(cooldown),
        "PAPER_MAX_DRAWDOWN_PCT": f"{config.paper_max_drawdown_pct:.2f}",
        "PAPER_DAILY_LOSS_PCT": f"{config.paper_daily_loss_pct:.2f}",
    }


def _current_settings(config: Settings) -> dict[str, str]:
    return {
        "PAPER_MAX_BET_FRACTION": f"{config.paper_max_bet_fraction:.2f}",
        "PAPER_MAX_CONSECUTIVE_LOSSES": str(config.paper_max_consecutive_losses),
        "PAPER_LOSS_STREAK_COOLDOWN_MINUTES": str(
            config.paper_loss_streak_cooldown_minutes
        ),
        "PAPER_MAX_DRAWDOWN_PCT": f"{config.paper_max_drawdown_pct:.2f}",
        "PAPER_DAILY_LOSS_PCT": f"{config.paper_daily_loss_pct:.2f}",
    }


def _recommendation_reason(evidence: LedgerEvidence) -> str:
    if evidence.decided < 20:
        return "표본 20건 미만: 증액 없이 보수 설정 유지"
    if evidence.pnl < 0:
        return "누적 PnL 음수: 1회 노출 3%, 연속손실 3회, 60분 쿨다운 유지"
    if evidence.win_rate < 55.0:
        return "승률 55% 미만: 리스크 확대 근거 부족"
    return "성과 양호: 현 제한값 유지, 자동 증액 없음"


def build_committee_review(config: Settings = settings) -> str:
    try:
        return build_codex_committee_review(config)
    except Exception as error:
        fallback = _build_static_committee_review(config)
        return (
            "⚠️ Codex 위원회 리뷰 실행 실패, 내부 집계 fallback 사용\n"
            f"사유: {str(error)[:300]}\n\n"
            + fallback
        )


def _build_static_committee_review(config: Settings = settings) -> str:
    evidence = collect_evidence(config)
    current = _current_settings(config)
    proposed = proposed_settings(config, evidence)
    generated_at = int(time.time())
    changes = [f"{key}: {current[key]} -> {proposed[key]}" for key in APPLY_KEYS
               if current[key] != proposed[key]]
    proposal = {
        "bot": config.paper_strategy_id,
        "generated_at": generated_at,
        "settings": proposed,
        "evidence": evidence.__dict__,
    }
    REVIEW_PROPOSAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_PROPOSAL_PATH.write_text(
        json.dumps(proposal, indent=2, sort_keys=True), encoding="utf-8"
    )
    mode = "LIVE" if config.live_trading_enabled and not config.live_dry_run else "PAPER"
    lines = [
        f"🧭 위원회 리뷰 요청: {config.paper_strategy_id} [{mode}]",
        f"근거 DB: {config.paper_ledger_db}",
        "",
        "1) 리스크 위원회",
        f"- 결정 {evidence.decided}건 | 승/패/손절 {evidence.wins}/{evidence.losses}/{evidence.stops} "
        f"| 승률 {evidence.win_rate:.1f}%",
        f"- 결정 stake {evidence.stake:.2f} | PnL {evidence.pnl:+.2f} "
        f"| stake ROI {evidence.roi_on_stake:+.2f}%",
        "",
        "2) 실행/스킵 근거",
        f"- 대기 {evidence.pending} | 스킵 {evidence.skips} "
        f"(mixed {evidence.mixed}, risk {evidence.risk_skips}, no_market {evidence.no_market})",
    ]
    if config.live_trading_enabled:
        wallet = "n/a" if evidence.wallet_usdc is None else f"${evidence.wallet_usdc:.2f}"
        pos_value = (
            "n/a" if evidence.positions_value is None else f"${evidence.positions_value:.2f}"
        )
        lines += [
            f"- 실체결 {evidence.live_fills}건 | 체결 USDC {evidence.live_usdc:.2f} "
            f"| 오류/미체결 {evidence.live_errors}",
            f"- 최신 지갑 {wallet} | positions_value {pos_value}",
        ]
    lines += [
        "",
        "3) 권고",
        f"- 판단: {_recommendation_reason(evidence)}",
        "- 현재: " + ", ".join(f"{key}={value}" for key, value in current.items()),
        "- 권고: " + ", ".join(f"{key}={value}" for key, value in proposed.items()),
        "- 변경: " + ("; ".join(changes) if changes else "없음"),
        "",
        "승인 적용: /apply_review",
    ]
    return "\n".join(lines)


def build_codex_committee_review(config: Settings = settings) -> str:
    snapshot = build_evidence_snapshot(config)
    fallback = snapshot["fallback_rule_proposal"]
    codex_response = _run_codex_committee(snapshot)
    proposed = _validate_settings(codex_response.get("settings", {}), fallback)
    current = snapshot["current_settings"]
    changes = [f"{key}: {current[key]} -> {proposed[key]}" for key in APPLY_KEYS
               if current[key] != proposed[key]]
    proposal = {
        "bot": config.paper_strategy_id,
        "generated_at": int(time.time()),
        "source": "codex_exec",
        "settings": proposed,
        "evidence": snapshot,
        "report": str(codex_response.get("report", "")).strip(),
    }
    REVIEW_PROPOSAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_PROPOSAL_PATH.write_text(
        json.dumps(proposal, indent=2, sort_keys=True), encoding="utf-8"
    )
    report = proposal["report"] or "Codex 위원회가 빈 리포트를 반환했습니다."
    return (
        "🧭 Codex 위원회 리뷰 완료\n"
        f"대상: {config.paper_strategy_id} [{snapshot['mode']}]\n"
        f"근거 파일: {REVIEW_EVIDENCE_PATH}\n\n"
        f"{report}\n\n"
        "- 권고: " + ", ".join(f"{key}={value}" for key, value in proposed.items()) + "\n"
        "- 변경: " + ("; ".join(changes) if changes else "없음") + "\n\n"
        "승인 적용: /apply_review"
    )


def _update_env_text(text: str, updates: dict[str, str]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(line)
    for key in APPLY_KEYS:
        if key in updates and key not in seen:
            lines.append(f"{key}={updates[key]}")
    return "\n".join(lines) + "\n"


def apply_committee_review(env_path: str | Path = ".env") -> str:
    if not REVIEW_PROPOSAL_PATH.exists():
        return "적용할 위원회 제안이 없습니다. 먼저 /committee_review 를 실행하세요."
    proposal = json.loads(REVIEW_PROPOSAL_PATH.read_text(encoding="utf-8"))
    updates = {key: str(proposal["settings"][key]) for key in APPLY_KEYS}
    path = Path(env_path)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    new = _update_env_text(old, updates)
    if old != new:
        path.write_text(new, encoding="utf-8")
    changed = "변경 적용" if old != new else "변경 없음"
    return (
        f"✅ 위원회 제안 승인 완료 ({changed})\n"
        + "\n".join(f"{key}={updates[key]}" for key in APPLY_KEYS)
        + "\n봇을 재구동합니다."
    )
