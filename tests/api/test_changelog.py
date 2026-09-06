"""`GET /v1/dq/changelog` (`plans/05-ui.md` done-when 1).

The panel is the evidence for locked decision 1 — raw immutable, clean derived, reproducible
from file plus ruleset. These assert the two decisions the plan settled about it: that the
route returns counts rather than one row per record, and that it is read-only.
"""

from __future__ import annotations

DEDUPE_FIXTURE = "unq_exact_duplicate.csv"
DEFECT_FIXTURE = "con_high_lt_low.csv"


def test_the_changelog_reports_counts_per_rule_trade_date_and_action(client, upload):
    upload(DEDUPE_FIXTURE)

    response = client.get("/v1/dq/changelog")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"], "defaults to the latest succeeded run"
    assert body["data"], "the dedupe fixture must produce at least one decision"

    for row in body["data"]:
        assert {"contract_id", "trade_date", "rule_id", "action", "records"} <= set(row)
        assert row["records"] >= 1
        assert row["action"] in ("exclude", "dedupe_drop", "coerce", "impute")

    # Aggregated, not per record: one row per (contract, date, frequency, rule, action).
    keys = [
        (r["contract_id"], r["trade_date"], r["frequency"], r["rule_id"], r["action"])
        for r in body["data"]
    ]
    assert len(keys) == len(set(keys))


def test_a_dedupe_decision_is_labelled_from_the_rule_catalogue(client, upload):
    """The wording lives with the rule, never as copy in a widget."""
    upload(DEDUPE_FIXTURE)
    body = client.get("/v1/dq/changelog").json()

    dedupe = [r for r in body["data"] if r["action"] == "dedupe_drop"]
    assert dedupe, "the exact-duplicate fixture should dedupe"
    for row in dedupe:
        assert row["rule_id"] == "UNQ.EXACT_DUPLICATE"
        assert row["label"], "label comes from dq_rule.name"


def test_exclusions_are_recorded_for_an_error_severity_defect(client, upload):
    upload(DEFECT_FIXTURE)
    body = client.get("/v1/dq/changelog").json()

    excluded = [r for r in body["data"] if r["action"] == "exclude"]
    assert excluded, "an error-severity finding excludes by the §1 severity default"
    assert sum(r["records"] for r in excluded) >= 1


def test_the_changelog_is_read_only(client, upload):
    """Cleaning is automatic policy driven by severity, so there is nothing to post to."""
    upload(DEDUPE_FIXTURE)
    assert client.post("/v1/dq/changelog").status_code == 405
    assert client.delete("/v1/dq/changelog").status_code == 405


def test_the_changelog_filters_by_contract_and_window(client, upload):
    upload(DEDUPE_FIXTURE)
    everything = client.get("/v1/dq/changelog").json()
    assert everything["data"]

    contract = everything["data"][0]["contract_id"]
    scoped = client.get("/v1/dq/changelog", params={"contract": contract}).json()
    assert scoped["data"]
    assert {r["contract_id"] for r in scoped["data"]} == {contract}

    absent = client.get(
        "/v1/dq/changelog", params={"start": "1990-01-01", "end": "1990-01-02"}
    ).json()
    assert absent["data"] == [] and absent["total"] == 0


def test_a_past_run_stays_inspectable_after_a_later_one_supersedes_it(client, upload):
    upload(DEDUPE_FIXTURE)
    first = client.get("/v1/dq/changelog").json()
    first_run = first["run_id"]

    again = client.post("/v1/dq/runs")
    assert again.status_code == 200
    latest = client.get("/v1/dq/changelog").json()

    assert latest["run_id"] != first_run, "the default follows the newest succeeded run"
    pinned = client.get("/v1/dq/changelog", params={"run_id": first_run}).json()
    assert pinned["run_id"] == first_run
    assert pinned["data"] == first["data"]


def test_an_empty_store_answers_rather_than_failing(client):
    body = client.get("/v1/dq/changelog").json()
    assert body["run_id"] is None
    assert body["data"] == [] and body["total"] == 0


def test_the_changelog_is_paginated(client, upload):
    upload(DEDUPE_FIXTURE)
    page = client.get("/v1/dq/changelog", params={"limit": 1}).json()
    assert page["limit"] == 1 and page["offset"] == 0
    assert len(page["data"]) <= 1
    assert page["total"] >= len(page["data"])
