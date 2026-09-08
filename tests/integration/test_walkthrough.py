"""The journey a user actually takes, over a real socket and a real file.

Nothing here is stubbed on either side. `LoupeClient` builds the multipart body, uvicorn parses
it, DuckDB writes to disk, and the assertions read the answers back over HTTP. That is the one
seam the rest of the suite cannot reach: `tests/ui/` replaces the client with a fake that never
builds a request, and `tests/api/` replaces the transport with an in-process `TestClient`.
Between them, `LoupeClient.create_batch` → HTTP → FastAPI `UploadFile` has no coverage at all.

These tests are slow by the standards of the other tiers and there are deliberately few of
them. They cover seams; behaviour belongs in the faster tiers that already own it.
"""

from __future__ import annotations

import pytest

MINUTE = "rec_corroboration_minute.csv"
DAILY = "rec_corroboration_daily.csv"


# --------------------------------------------------------------------- the upload seam


def test_a_preview_crosses_the_wire_and_commits_nothing(api_client, fixture_path):
    """Preview is the step where a user learns what a file cannot do, before committing.

    It is also a multipart POST, so it exercises the same body-building path the upload does —
    and it must leave the store exactly as it found it.
    """
    path = fixture_path(MINUTE)
    before = api_client.health()["records"]

    preview = api_client.preview(path.name, path.read_bytes())

    assert preview["inferred_frequency"]["value"] == "minute"
    assert preview["contracts_detected"]
    assert preview["verdict"] == "accept"
    assert api_client.health()["records"] == before, "previewing must not ingest"


def test_a_real_multipart_upload_lands_and_is_readable(api_client, upload_file):
    """The seam both other tiers simulate, end to end.

    `FakeClient.create_batch` records a call and returns a canned dict; `TestClient` posts
    without a socket. Neither would notice a defect in how the real client encodes the body or
    reads the response, which is what broke on the first run of the app.
    """
    before = api_client.health()["records"]
    batch = upload_file(MINUTE)

    assert batch["status"] == "succeeded"
    assert batch["rows_accepted"] > 0
    assert batch["rows_rejected"] == 0

    health = api_client.health()
    assert health["records"] == before + batch["rows_accepted"]
    assert health["batches"] >= 1


def test_the_same_file_twice_is_refused_as_a_problem_the_client_can_read(
    api_client, upload_file, fixture_path
):
    """A refusal has to survive the wire as an `ApiProblem`, not as an exception or a 500.

    Ingest enforces `UNQ.DUPLICATE_FILE` on the file hash, and the UI renders the refusal in
    place. That round trip — domain error, RFC 7807 body, `ApiProblem` with its `code` intact —
    is only real when there is an HTTP layer between the two ends.
    """
    from loupe.ui.client import ApiProblem

    upload_file(MINUTE)
    path = fixture_path(MINUTE)

    with pytest.raises(ApiProblem) as raised:
        api_client.create_batch(path.name, path.read_bytes())

    problem = raised.value
    assert problem.status == 409
    assert problem.code == "STR.DUPLICATE_FILE"
    # The sentence is the point. Before this tier existed the client discarded the body and
    # the UI rendered a bare "Conflict", telling the user no without telling them why.
    assert "already loaded" in str(problem)
    assert problem.meta.get("batch_id"), "the refusal names the batch that already holds it"


# ------------------------------------------------------------------- the whole journey


def test_the_walkthrough_from_an_empty_store_to_a_reconciled_book(api_client, upload_file):
    """Bootstrap, upload both grains, re-run, read the dashboard — over HTTP throughout.

    The step in the middle is the one worth having a test for. `POST /v1/ingest/batches` runs
    the rules **scoped to that batch**, so uploading the daily file cannot put reconciliation
    in scope: at that moment the run has never seen the minute records. It takes a corpus-wide
    `POST /v1/dq/runs` for the two grains to be compared, and a user who uploads a second file
    and expects the score to change is right to be surprised.
    """
    # One `bootstrap=True` and the store is ready to ingest: schema, reference data and the
    # rule catalogue. Asserted first so the journey below starts from the documented state.
    assert api_client.health()["rules_seeded"] is True

    upload_file(MINUTE)
    upload_file(DAILY)

    scoped = api_client.summary(contract="ESZ25")
    per_batch = {s["scope_signature"] for s in scoped["slices"] if s["contract_id"] == "ESZ25"}
    assert per_batch, "the summary must answer after an upload"

    # The corpus-wide re-run is what makes the two grains comparable.
    run = api_client._request("POST", "/dq/runs")
    assert run["status"] == "succeeded"

    summary = api_client.summary(contract="ESZ25")
    slices = [s for s in summary["slices"] if s["contract_id"] == "ESZ25"]
    assert slices
    for sliced in slices:
        assert "reconciliation" in sliced["dimensions_in_scope"]
        assert sliced["scope_signature"].endswith("+rec")
        assert sliced["weight_denominator"] == pytest.approx(1.20)

    row = next(c for c in summary["contracts"] if c["contract_id"] == "ESZ25")
    assert sorted(row["frequencies"]) == ["daily", "minute"]
    # No `score`, and that is the right answer rather than a gap: the fixture holds a handful
    # of records against §11.5's `min_records` floor, so every slice reports insufficient data
    # instead of a number. A score computed from five rows would be precise and meaningless.
    assert all(s["insufficient_data"] for s in slices)
    assert row["score"] is None


def test_dual_grain_review_stays_aligned_over_http(api_client, upload_file):
    upload_file(MINUTE)
    upload_file(DAILY)
    api_client._request("POST", "/dq/runs")

    for frequency, source in (("minute", "derived_from_minute"), ("daily", "supplied_daily")):
        checks = api_client.checks(
            contract="ESZ25", family="invalid", frequency=frequency
        )
        bars = api_client.bars_daily(contract="ESZ25", frequency=frequency)

        assert checks["scope"]["frequency"] == frequency
        assert checks["scope"]["frequency_defaulted"] is False
        assert {row["family"] for row in checks["issues"]} <= {"invalid"}
        assert bars["scope"]["frequency"] == frequency
        assert bars["meta"]["bar_source"] == source


def test_a_daily_finding_carries_its_corroboration_over_the_wire(api_client, upload_file):
    """§8.7's qualification has to survive serialisation, not just exist in `quality`.

    Absence is meaningful here too: a minute-grain finding must come back with no
    `corroboration` key rather than with a null-ish placeholder, because absent means *does not
    apply* and `not_comparable` means *applies and could not be evaluated*.
    """
    upload_file(MINUTE)
    upload_file(DAILY)
    api_client._request("POST", "/dq/runs")

    findings = api_client.findings(
        contract="ESZ25", rule_id="CON.CLOSE_OUT_OF_RANGE", limit=100
    )["data"]
    by_grain = {f["frequency"]: f for f in findings}
    assert {"daily", "minute"} <= set(by_grain), "the fixture holds this rule at both grains"

    daily = by_grain["daily"]["corroboration"]
    assert daily is not None
    assert daily["state"] in ("confirmed", "disputed", "not_comparable")
    assert daily["reason"]

    assert by_grain["minute"]["corroboration"] is None


def test_the_insights_routes_answer_on_a_real_corpus(api_client, upload_file):
    """Both reports must answer over HTTP with their contract shape.

    Row-level behaviour — lift arithmetic, generator triggers — is covered in
    `tests/api/test_insights.py` against a corpus built to produce it. What this asserts is
    that the routes are reachable, serialise, and stay report-only on the wire.
    """
    upload_file(MINUTE)
    upload_file(DAILY)
    api_client._request("POST", "/dq/runs")

    patterns = api_client.get("/insights/patterns")
    assert set(patterns) == {"scope", "data", "total", "meta"}
    assert patterns["meta"]["min_lift"]

    suggestions = api_client.suggestions()
    assert set(suggestions) == {"scope", "data", "total"}
    for suggestion in suggestions["data"]:
        assert "actions" not in suggestion


# ------------------------------------------------------------------------ persistence


def test_what_an_upload_wrote_survives_the_process_that_wrote_it(store_path, fixture_path):
    """Everything a request materialises has to be in the file, not in the handle.

    This is the class the `build_bars`-on-upload defect belonged to: work done during one
    request that a later request — or a later *start* — expects to find. Every other tier is
    `:memory:` and closes with the test, so none of them can tell the difference.

    No live server here, deliberately. DuckDB is single-writer per file, so proving durability
    means closing the writer and opening the file again — which a fixture holding a socket open
    cannot do. `TestClient` is enough: the question is what reached the disk, not what crossed
    the wire, and the wire is covered above.
    """
    from fastapi.testclient import TestClient

    from loupe.api import create_app
    from loupe.data import connect

    con = connect(store_path)
    with TestClient(create_app(con, bootstrap=True)) as client:
        for name in (MINUTE, DAILY):
            path = fixture_path(name)
            with path.open("rb") as handle:
                response = client.post(
                    "/v1/ingest/batches",
                    files={"file": (path.name, handle, "text/csv")},
                    params={"validate": True},
                )
            assert response.status_code in (200, 201), response.text
        assert client.post("/v1/dq/runs").status_code in (200, 201)
    con.close()

    reopened = connect(store_path)
    try:
        counts = {
            table: reopened.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "stage.market_record",
                "dq.dq_finding",
                "mart.bar_daily",
                "mart.dq_metric_daily",
            )
        }
    finally:
        reopened.close()

    assert counts["stage.market_record"] > 0
    assert counts["dq.dq_finding"] > 0
    # `build_bars` runs inside the upload request; its rows have to be in the file, or the
    # charts are empty on the next start for a file that loaded perfectly.
    assert counts["mart.bar_daily"] > 0
    assert counts["mart.dq_metric_daily"] > 0, "the per-day metrics are persisted, not derived"
