from codex_btc5_v2.polymarket import (
    Round, parse_round_slug, parse_market, best_ask_from_payload, outcome_from_market,
)

MARKET = {
    "slug": "btc-updown-5m-1781950200",
    "clobTokenIds": "[\"tokenUP\", \"tokenDOWN\"]",
    "outcomes": "[\"Up\", \"Down\"]",
    "conditionId": "0xabc",
    "outcomePrices": None,
    "acceptingOrders": True,
}


def test_parse_round_slug():
    assert parse_round_slug("btc-updown-5m-1781950200") == (1781950200, 1781950500)
    assert parse_round_slug("eth-updown-5m-1781950200") is None
    assert parse_round_slug(None) is None
    assert parse_round_slug("garbage") is None


def test_parse_market_maps_up_down():
    r = parse_market(MARKET)
    assert isinstance(r, Round)
    assert r.slug == "btc-updown-5m-1781950200"
    assert r.start_ts == 1781950200 and r.end_ts == 1781950500
    assert r.up_token_id == "tokenUP"
    assert r.down_token_id == "tokenDOWN"
    assert r.condition_id == "0xabc"


def test_parse_market_handles_reversed_outcomes():
    m = dict(MARKET, outcomes="[\"Down\", \"Up\"]", clobTokenIds="[\"tokDOWN\", \"tokUP\"]")
    r = parse_market(m)
    assert r.up_token_id == "tokUP"
    assert r.down_token_id == "tokDOWN"


def test_parse_market_rejects_non_btc5m():
    assert parse_market({"slug": "eth-updown-5m-1781950200"}) is None


def test_best_ask_from_payload():
    assert best_ask_from_payload({"price": "0.39"}) == 0.39
    assert best_ask_from_payload({}) is None
    assert best_ask_from_payload({"price": "x"}) is None


def test_outcome_from_market():
    won_up = dict(MARKET, outcomePrices="[\"1\", \"0\"]")
    won_down = dict(MARKET, outcomePrices="[\"0\", \"1\"]")
    pending = dict(MARKET, outcomePrices="[\"0.5\", \"0.5\"]")
    assert outcome_from_market(won_up) == "UP"
    assert outcome_from_market(won_down) == "DOWN"
    assert outcome_from_market(pending) is None
    assert outcome_from_market(dict(MARKET, outcomePrices=None)) is None
