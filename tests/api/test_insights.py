"""The two insights routes (`specs/api-contract.md` §7, done-when 4).

Contract tests: the envelope, the filters and the v1 cut. They run against the real app over
the real store, so a handler that failed to call `quality` would fail here rather than pass
against a mock of itself.

The v1 cut is asserted twice over, from both directions. The routes must **answer** — they sat
mounted and empty through slice 5, and a test that only checked for absent apply routes would
have passed the whole time. And they must expose no way to act, which is checked over the
serialised body rather than by naming one key, because any action-shaped value is enough for a
client to build a button on.
"""

from __future__ import annotations

import pytest

from loupe.quality import assess

SETTLEMENT_PAIR = (
    "insights_pattern_settlement_minute.csv",
    "insights_pattern_settlement_daily.csv",
)


@pytest.fixture
def reported(client, api_con, upload):
    """A corpus whose vendor close is a settlement on 24 sessions, run and scored."""
    for name in SETTLEMENT_PAIR:
        assert upload(name).status_code in (200, 201)
    assess(api_con, min_records=1)
    return client


# ------------------------------------------------------------------------------ patterns


def test_patterns_returns_its_contract_shape(reported):
    body = reported.get("/v1/insights/patterns").json()

    assert set(body) == {"scope", "data", "total", "meta"}
    assert body["total"] == len(body["data"])
    assert body["data"], "the route must answer with rows, not merely with a 200"

    pattern = body["data"][0]
    assert set(pattern) == {
        "pattern_id",
        "rule_id",
        "dimension",
        "bucket",
        "share_of_findings",
        "share_of_records",
        "lift",
        "support",
        "distinct_days",
        "narrative",
        "confidence",
    }
    assert pattern["lift"] >= 1.0
    assert pattern["narrative"]


def test_the_thresholds_are_echoed_so_an_empty_list_is_readable(reported):
    """"Nothing concentrates" and "the thresholds excluded everything" are different answers."""
    body = reported.get("/v1/insights/patterns", params={"min_lift": 99}).json()
    assert body["data"] == []
    assert body["meta"]["min_lift"] == 99


def test_min_lift_filters_from_both_sides(reported):
    """The measured lift on this corpus is 4.0."""
    admitted = reported.get("/v1/insights/patterns", params={"min_lift": 3}).json()
    rejected = reported.get("/v1/insights/patterns", params={"min_lift": 5}).json()
    assert admitted["total"] > 0
    assert rejected["total"] == 0


def test_min_support_filters_from_both_sides(reported):
    """Support is 24 findings across 24 sessions."""
    admitted = reported.get("/v1/insights/patterns", params={"min_support": 20}).json()
    rejected = reported.get("/v1/insights/patterns", params={"min_support": 25}).json()
    assert admitted["total"] > 0
    assert rejected["total"] == 0


def test_the_contract_filter_narrows_the_scope(reported):
    """Both sides again: a contract that holds the findings, and one that holds none."""
    mine = reported.get("/v1/insights/patterns", params={"contract": "ESZ25"}).json()
    other = reported.get("/v1/insights/patterns", params={"contract": "CLZ25"}).json()
    assert mine["total"] > 0
    assert mine["scope"]["contracts"] == ["ESZ25"]
    assert other["total"] == 0


def test_a_nonsense_lift_is_refused_by_the_signature(reported):
    """`ge=1.0`: a lift below one is not a concentration, it is a dilution."""
    assert reported.get("/v1/insights/patterns", params={"min_lift": 0}).status_code == 422


# --------------------------------------------------------------------------- suggestions


def test_suggestions_returns_its_contract_shape(reported):
    body = reported.get("/v1/insights/suggestions").json()

    assert set(body) == {"scope", "data", "total"}
    assert body["data"], "the route must answer with rows, not merely with a 200"

    suggestion = body["data"][0]
    assert set(suggestion) == {
        "suggestion_id",
        "from_pattern",
        "kind",
        "title",
        "rationale",
        "evidence",
        "proposed_change",
        "expected_effect",
        "confidence",
    }
    assert suggestion["rationale"]
    assert set(suggestion["proposed_change"]) == {"target", "operation", "params"}


def test_a_suggestion_cites_a_pattern_the_other_route_returns(reported):
    """`from_pattern` has to name something a client can actually look up."""
    patterns = reported.get("/v1/insights/patterns").json()["data"]
    suggestions = reported.get("/v1/insights/suggestions").json()["data"]
    ids = {p["pattern_id"] for p in patterns}
    assert suggestions
    for suggestion in suggestions:
        assert suggestion["from_pattern"] in ids


def test_the_suggestions_payload_exposes_no_apply_or_dismiss_link(reported):
    """v1 identifies and suggests; it does not mutate (locked decision 10).

    Asserted over the whole serialised body: a missing `actions` key is not enough, because a
    link anywhere in the payload would be all a client needs.
    """
    response = reported.get("/v1/insights/suggestions")
    body = response.json()
    assert body["data"]
    for suggestion in body["data"]:
        assert "actions" not in suggestion
    rendered = response.text.lower()
    for word in ("apply", "dismiss", "\"href\"", "\"links\""):
        assert word not in rendered, f"{word!r} appears in a report-only payload"


def test_the_apply_and_dismiss_routes_do_not_exist(reported):
    """Absent rather than present-and-refusing: a 405 invites a client to keep the button."""
    suggestion = reported.get("/v1/insights/suggestions").json()["data"][0]
    identifier = suggestion["suggestion_id"]
    for verb in ("apply", "dismiss"):
        response = reported.post(f"/v1/insights/suggestions/{identifier}/{verb}")
        assert response.status_code == 404


def test_an_empty_store_answers_with_an_empty_report(client):
    """No findings is not an error, and not a 404: it is a report with nothing in it."""
    for path in ("/v1/insights/patterns", "/v1/insights/suggestions"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["data"] == []
