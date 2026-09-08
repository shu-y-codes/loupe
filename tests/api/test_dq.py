"""Data-quality contract tests (`specs/api-contract.md` §6).

Findings are read-only in v1. That is asserted as *absence of a route*, not as a 405 on one
that exists: an endpoint that answers at all invites a client to keep the button.
"""

from __future__ import annotations

MINUTE_FIXTURE = "insights_vwap_window.csv"
DEFECT_FIXTURE = "con_close_out_of_range.csv"


def test_health_reports_store_state(client):
    body = client.get("/v1/health").json()
    assert body["status"] == "ok"
    assert body["schema_applied"] is True
    assert body["rules_seeded"] is True


def test_rules_returns_the_seeded_catalogue(client):
    body = client.get("/v1/dq/rules").json()
    assert body["total"] > 0
    rule = body["data"][0]
    assert {"rule_id", "dimension", "severity", "scope", "enabled"} <= set(rule)


def test_findings_are_paginated_and_read_only(client, upload):
    upload(DEFECT_FIXTURE)

    response = client.get("/v1/dq/findings")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100 and body["offset"] == 0
    assert body["total"] >= len(body["data"])

    # v1 has no write verb on findings, in either form.
    assert client.post("/v1/dq/findings").status_code == 405
    if body["data"]:
        finding_id = body["data"][0]["finding_id"]
        assert client.post(f"/v1/dq/findings/{finding_id}/review").status_code == 404


def test_a_finding_carries_the_evidence_to_cite_a_source_row(client, upload):
    upload(DEFECT_FIXTURE)
    data = client.get("/v1/dq/findings", params={"rule_id": "CON.CLOSE_OUT_OF_RANGE"}).json()
    assert data["total"] > 0

    finding = data["data"][0]
    assert finding["rule_id"] == "CON.CLOSE_OUT_OF_RANGE"
    assert finding["severity"]
    assert finding["status"] == "open"
    assert finding["details"], "evidence travels with the finding"
    assert finding["source"]["filename"], "the UI must be able to cite a named file"
    assert finding["source"]["source_row"] is not None


def test_findings_filter_by_rule_and_severity(client, upload):
    upload(DEFECT_FIXTURE)
    all_findings = client.get("/v1/dq/findings").json()
    filtered = client.get("/v1/dq/findings", params={"rule_id": "CON.CLOSE_OUT_OF_RANGE"}).json()
    assert filtered["total"] <= all_findings["total"]
    assert all(f["rule_id"] == "CON.CLOSE_OUT_OF_RANGE" for f in filtered["data"])


def test_unknown_finding_is_404(client):
    response = client.get("/v1/dq/findings/01900000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "STR.UNKNOWN_FINDING"


def test_summary_carries_the_scope_signature_with_the_score(client, upload):
    """Which dimensions were in scope is part of the score, not metadata about it."""
    upload(MINUTE_FIXTURE)

    body = client.get("/v1/dq/summary", params={"contract": "ESZ25"}).json()
    assert body["score_method"].startswith("weighted mean")
    assert body["slices"], "a validated batch must produce at least one scored slice"

    one = body["slices"][0]
    assert one["scope_signature"]
    assert one["dimensions_in_scope"]
    assert one["weight_denominator"] > 0
    assert set(one["dimensions"]) == set(one["dimensions_in_scope"])
    assert body["records"]["total"] > 0


def test_summary_says_so_when_nothing_has_been_validated(client):
    body = client.get("/v1/dq/summary").json()
    assert body["overall_score"] is None
    assert body["slices"] == []
    assert "POST /v1/dq/runs" in body["meta"]["reason"]


def test_reconciliation_is_out_of_scope_for_a_single_frequency_upload(client, upload):
    """Minute-only: the reconciliation weight leaves both sums, with a reason."""
    upload(MINUTE_FIXTURE)
    slices = client.get("/v1/dq/summary", params={"contract": "ESZ25"}).json()["slices"]
    one = slices[0]
    assert "reconciliation" not in one["dimensions_in_scope"]
    not_in_scope = {d["dimension"]: d["reason"] for d in one["dimensions_not_in_scope"]}
    assert "reconciliation" in not_in_scope
    assert not_in_scope["reconciliation"]


def test_metrics_group_by_is_echoed(client, upload):
    upload(DEFECT_FIXTURE)
    for group_by in ("day", "contract", "rule", "dimension", "frequency"):
        body = client.get("/v1/dq/metrics", params={"group_by": group_by}).json()
        assert body["group_by"] == group_by
        assert body["total"] == len(body["data"])


def test_a_run_blocks_and_returns_the_finished_run(client, upload):
    """`POST /dq/runs` returns a completed run, never a pending job handle."""
    upload(MINUTE_FIXTURE, validate=False)

    response = client.post("/v1/dq/runs")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "succeeded"
    assert body["finished_at"] is not None
    assert body["ruleset_hash"]
    assert "job_id" not in body and "poll_url" not in body

    fetched = client.get(f"/v1/dq/runs/{body['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == body["run_id"]


def test_a_run_rebuilds_bars_for_analytics(client, upload, api_con):
    """`POST /dq/runs` materialises `mart.bar_daily` for the run's scope."""
    upload(MINUTE_FIXTURE, validate=False)
    api_con.execute("DELETE FROM mart.bar_daily")
    assert api_con.execute("SELECT count(*) FROM mart.bar_daily").fetchone()[0] == 0

    assert client.post("/v1/dq/runs").status_code == 200

    response = client.get("/v1/analytics/bars/daily", params={"contract": "ESZ25"})
    assert response.status_code == 200
    assert response.json()["total"] > 0


def test_unknown_run_is_404(client):
    response = client.get("/v1/dq/runs/01900000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "STR.UNKNOWN_RUN"


def test_checks_echoes_grain_and_returns_selected_family_only(client, upload):
    upload("rec_corroboration_minute.csv")
    upload("rec_corroboration_daily.csv")
    assert client.post("/v1/dq/runs").status_code == 200

    for frequency, source in (("minute", "derived_from_minute"), ("daily", "supplied_daily")):
        checks = client.get(
            "/v1/dq/checks",
            params={
                "contract": "ESZ25",
                "family": "invalid",
                "frequency": frequency,
            },
        )
        assert checks.status_code == 200, checks.text
        body = checks.json()
        assert body["scope"]["frequency"] == frequency
        assert body["scope"]["frequency_defaulted"] is False
        assert {row["family"] for row in body["issues"]} <= {"invalid"}
        picture = body["overlay"]["picture"]
        if picture["kind"] == "invalid_cell":
            assert picture["evidence_frequency"] == frequency
            assert picture["evidence_source"] == (
                "vendor" if frequency == "daily" else "source_record"
            )

        bars = client.get(
            "/v1/analytics/bars/daily",
            params={"contract": "ESZ25", "frequency": frequency},
        ).json()
        assert bars["scope"]["frequency"] == frequency
        assert bars["meta"]["bar_source"] == source


def test_checks_defaults_dual_grain_to_minute(client, upload):
    upload("rec_corroboration_minute.csv")
    upload("rec_corroboration_daily.csv")
    assert client.post("/v1/dq/runs").status_code == 200

    body = client.get(
        "/v1/dq/checks", params={"contract": "ESZ25", "family": "invalid"}
    ).json()

    assert body["scope"]["frequency"] == "minute"
    assert body["scope"]["frequency_defaulted"] is True
