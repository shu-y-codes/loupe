"""Analytics contract tests (`specs/api-contract.md` §5).

The centrepiece is §5.2's refusal. A rolling 15-minute VWAP over a daily-only contract is
not an empty series and not a zero-filled one: it is a 422 that says why and what to upload.
These tests hold all four outcomes apart, because collapsing any two of them is the failure
the publish gate and its capability state exist to prevent.
"""

from __future__ import annotations

from loupe.api import PROBLEM_MEDIA_TYPE
from loupe.quality import run_rules

MINUTE_FIXTURE = "insights_vwap_window.csv"
DAILY_FIXTURE = "con_derived_bar_invalid_vendor.csv"
MISALIGNED_FIXTURE = "tim_timezone_misaligned.csv"


def test_upload_materialises_bars_without_a_manual_build(client, upload):
    """Ingest calls `build_bars` — analytics must not depend on a test-only rebuild."""
    upload(MINUTE_FIXTURE)

    response = client.get("/v1/analytics/bars/daily", params={"contract": "ESZ25"})
    assert response.status_code == 200
    assert response.json()["total"] > 0


def test_vwap_returns_the_line_for_a_minute_contract(client, upload):
    upload(MINUTE_FIXTURE)

    response = client.get("/v1/analytics/vwap", params={"contract": "ESZ25"})
    assert response.status_code == 200

    body = response.json()
    assert body["window"] == "15m"
    assert body["window_type"] == "trailing_time_range_inclusive"
    assert body["price_basis"] == "typical"
    assert body["partition"] == ["contract_id", "trade_date"]
    assert body["total"] > 0
    assert {"ts_utc", "vwap", "window_volume", "window_records", "is_warmup"} <= set(
        body["data"][0]
    )


def test_vwap_on_a_daily_only_contract_is_refused_in_place(client, upload):
    """422, not 404 or 400: the request is valid and the contract exists.

    The server understands it and cannot process it given the data currently held.
    """
    upload(DAILY_FIXTURE)

    response = client.get("/v1/analytics/vwap", params={"contract": "CLZ25"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)

    body = response.json()
    assert body["code"] == "CAP.FREQUENCY_UNAVAILABLE"
    assert body["type"] == "/errors/frequency-unavailable"
    assert body["status"] == 422
    assert "CLZ25" in body["detail"]
    assert "intraday" in body["detail"]
    # `meta` lets the client render a next action without a second call.
    assert body["meta"] == {
        "contract_id": "CLZ25",
        "requested_frequency": "minute",
        "frequencies_available": ["daily"],
        "substitute_offered": False,
    }
    assert body["instance"].startswith("/v1/analytics/vwap")


def test_the_refusal_is_not_an_empty_series(client, upload):
    """The distinction the capability state exists to make.

    A daily-only contract refuses; a contract with no records at all returns an empty 200.
    Same shape of question, deliberately different answers.
    """
    upload(DAILY_FIXTURE)

    refused = client.get("/v1/analytics/vwap", params={"contract": "CLZ25"})
    assert refused.status_code == 422

    absent = client.get("/v1/analytics/vwap", params={"contract": "NOSUCH26"})
    assert absent.status_code == 200
    assert absent.json()["data"] == []
    assert absent.json()["total"] == 0


def test_the_refusal_is_not_a_blocked_series(client, upload, api_con):
    """Blocked and unavailable are different states and render differently.

    A `critical` finding withholds a series that exists — 200, empty `data`, and the
    blocking rule named. A daily-only contract refuses with 422. Neither is "no data".
    """
    upload(MISALIGNED_FIXTURE, validate=False)
    run_rules(api_con)

    response = client.get("/v1/analytics/vwap", params={"contract": "ESZ25"})
    assert response.status_code == 200, "withheld is not refused"

    body = response.json()
    assert body["data"] == []
    assert body["blocked_sessions"], "a withheld session must be named, not silently dropped"
    assert "TIM.TIMEZONE_MISALIGNED" in body["blocked_sessions"][0]["blocking_rule_ids"]


def test_vwap_never_offers_a_substitute(client, upload):
    """No 15-*day* VWAP over daily bars standing in for the 15-minute line."""
    upload(DAILY_FIXTURE)
    body = client.get("/v1/analytics/vwap", params={"contract": "CLZ25"}).json()
    assert body["meta"]["substitute_offered"] is False


def test_bars_daily_echoes_the_scope_it_resolved(client, upload):
    upload(MINUTE_FIXTURE)

    response = client.get("/v1/analytics/bars/daily", params={"contract": "ESZ25"})
    assert response.status_code == 200

    body = response.json()
    scope = body["scope"]
    assert scope["basis"] == "clean"
    assert scope["frequency"] == "minute"
    assert scope["frequency_defaulted"] is True, "the caller omitted it; say so"
    assert body["meta"]["bar_source"] == "derived_from_minute"
    assert body["total"] == len(body["data"])
    if body["data"]:
        bar = body["data"][0]
        assert {"open", "high", "low", "close", "volume"} <= set(bar)
        assert "completeness_pct" in bar and "finding_count" in bar


def test_bars_frequency_daily_returns_the_supplied_bars(client, upload):
    """`frequency=minute` aggregates the tape; `frequency=daily` returns what was supplied.

    Both return daily bars and are not the same numbers (§2.1).
    """
    upload(DAILY_FIXTURE)

    response = client.get(
        "/v1/analytics/bars/daily", params={"contract": "CLZ25", "frequency": "daily"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["frequency"] == "daily"
    assert body["scope"]["frequency_defaulted"] is False
    assert body["meta"]["bar_source"] == "supplied_daily"


def test_compare_frequency_refuses_when_only_one_grain_is_held(client, upload):
    """Same `CAP.*` refusal as VWAP: comparing needs both sides."""
    upload(DAILY_FIXTURE)

    response = client.get(
        "/v1/analytics/compare", params={"contract": "CLZ25", "compare": "frequency"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "CAP.FREQUENCY_UNAVAILABLE"


def test_compare_basis_lines_raw_and_clean_up(client, upload):
    upload(MINUTE_FIXTURE)

    response = client.get(
        "/v1/analytics/compare", params={"contract": "ESZ25", "compare": "basis"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["compare"] == "basis"
    assert body["total"] == len(body["data"])
    assert body["differing"] <= body["total"]
