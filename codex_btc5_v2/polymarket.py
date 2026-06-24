from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

_SLUG = re.compile(r"^btc-updown-5m-(\d{9,11})$")
ROUND_SECONDS = 5 * 60


@dataclass(frozen=True)
class Round:
    slug: str
    start_ts: int
    end_ts: int
    up_token_id: str | None
    down_token_id: str | None
    condition_id: str | None


def _loads_maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def parse_round_slug(slug: str | None) -> tuple[int, int] | None:
    if not slug:
        return None
    match = _SLUG.match(slug)
    if not match:
        return None
    start = int(match.group(1))
    return start, start + ROUND_SECONDS


def _token_ids(market: dict) -> list[str]:
    tokens = _loads_maybe_json(market.get("clobTokenIds") or market.get("tokenIds") or [])
    if isinstance(tokens, list):
        return [str(t) for t in tokens if str(t)]
    return []


def _map_up_down(tokens: list[str], outcomes: list) -> tuple[str | None, str | None]:
    if len(tokens) >= 2 and len(outcomes) >= 2:
        up_idx = next((i for i, o in enumerate(outcomes) if str(o).strip().lower() == "up"), 0)
        up_idx = up_idx if up_idx in (0, 1) else 0
        down_idx = 1 - up_idx
        return tokens[up_idx], tokens[down_idx]
    if len(tokens) >= 2:
        return tokens[0], tokens[1]
    return (tokens[0] if tokens else None), None


def parse_market(market: dict) -> Round | None:
    slug = market.get("slug") or market.get("market_slug")
    window = parse_round_slug(slug)
    if window is None:
        return None
    start_ts, end_ts = window
    tokens = _token_ids(market)
    outcomes = _loads_maybe_json(market.get("outcomes") or [])
    if not isinstance(outcomes, list):
        outcomes = []
    up_token, down_token = _map_up_down(tokens, outcomes)
    return Round(
        slug=slug,
        start_ts=start_ts,
        end_ts=end_ts,
        up_token_id=up_token,
        down_token_id=down_token,
        condition_id=market.get("conditionId") or market.get("condition_id"),
    )


def best_ask_from_payload(payload: dict) -> float | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("price")
    if raw is None:
        return None
    try:
        value = float(raw)
        return value if math.isfinite(value) and 0.0 < value <= 1.0 else None
    except (TypeError, ValueError):
        return None


def outcome_from_market(market: dict) -> str | None:
    outcomes = _loads_maybe_json(market.get("outcomes") or [])
    prices = _loads_maybe_json(market.get("outcomePrices") or [])
    if not isinstance(outcomes, list) or not isinstance(prices, list):
        return None
    if not outcomes or len(outcomes) != len(prices):
        return None
    for outcome, price in zip(outcomes, prices):
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value >= 0.99:
            return "UP" if str(outcome).strip().lower() == "up" else "DOWN"
    return None


from datetime import datetime, timezone

import requests  # noqa: E402

from .config import Settings, settings  # noqa: E402


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _markets(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("markets") or payload.get("data") or []
    return []


def find_open_round(now_ts: int, config: Settings = settings, session=requests) -> Round | None:
    response = session.get(
        f"{config.gamma_base_url}/markets",
        params={
            "active": "true",
            "closed": "false",
            "limit": 200,
            "order": "endDate",
            "ascending": "true",
            "end_date_min": _iso(now_ts),
        },
        timeout=config.http_timeout,
    )
    response.raise_for_status()
    for market in _markets(response.json()):
        if not isinstance(market, dict):
            continue
        rnd = parse_market(market)
        if rnd is not None and rnd.start_ts <= now_ts < rnd.end_ts:
            return rnd
    return None


def token_best_ask(token_id: str, config: Settings = settings, session=requests) -> float | None:
    if not token_id:
        return None
    response = session.get(
        f"{config.clob_base_url}/price",
        params={"token_id": token_id, "side": "buy"},
        timeout=config.http_timeout,
    )
    response.raise_for_status()
    return best_ask_from_payload(response.json())


def token_best_bid(token_id: str, config: Settings = settings, session=requests) -> float | None:
    if not token_id:
        return None
    response = session.get(
        f"{config.clob_base_url}/price",
        params={"token_id": token_id, "side": "sell"},
        timeout=config.http_timeout,
    )
    response.raise_for_status()
    return best_ask_from_payload(response.json())


def bid_levels_from_book(payload: dict) -> list[tuple[float, float]]:
    """Extract (price, size) bid levels from a CLOB /book payload, best price first."""
    levels = []
    for row in (payload or {}).get("bids", []) or []:
        try:
            levels.append((float(row["price"]), float(row["size"])))
        except (KeyError, TypeError, ValueError):
            continue
    levels.sort(key=lambda lv: lv[0], reverse=True)
    return levels


def token_bid_levels(token_id: str, config: Settings = settings,
                     session=requests) -> list[tuple[float, float]] | None:
    """Real bid-side depth for a token, or None if unavailable."""
    if not token_id:
        return None
    try:
        response = session.get(
            f"{config.clob_base_url}/book",
            params={"token_id": token_id},
            timeout=config.http_timeout,
        )
        response.raise_for_status()
        return bid_levels_from_book(response.json())
    except Exception:
        return None


def entry_ask_for_side(rnd: Round, side: str, config: Settings = settings, session=requests) -> float | None:
    token_id = rnd.up_token_id if side == "UP" else rnd.down_token_id
    return token_best_ask(token_id, config, session)


def fetch_round_outcome(slug: str, config: Settings = settings, session=requests) -> str | None:
    # Resolved markets are dropped from a bare ?slug= query (Gamma excludes
    # closed markets by default), so closed=true is required to read the outcome.
    response = session.get(
        f"{config.gamma_base_url}/markets",
        params={"slug": slug, "closed": "true"},
        timeout=config.http_timeout,
    )
    response.raise_for_status()
    for market in _markets(response.json()):
        if isinstance(market, dict):
            outcome = outcome_from_market(market)
            if outcome is not None:
                return outcome
    return None
