"""Ingest contract tests (`specs/api-contract.md` §4).

Uploads are the only way records enter the store, and the write is synchronous: a 201 means
the load and its validation have finished, not that a job was queued.
"""

from __future__ import annotations

from loupe.api import PROBLEM_MEDIA_TYPE

MINUTE_FIXTURE = "insights_vwap_window.csv"
DAILY_FIXTURE = "con_derived_bar_invalid_vendor.csv"


def test_happy_path_upload_returns_201_with_the_finished_batch(upload):
    response = upload(MINUTE_FIXTURE)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] in ("succeeded", "partial")
    assert body["frequency"] == "minute"
    assert body["rows_accepted"] > 0
    assert body["contracts_detected"] == ["ESZ25"]
    # The four decisions a later reprocessing must reproduce are all on the summary.
    assert body["source_timezone"]
    assert body["ts_convention"]
    assert body["session_boundary"]
    # Synchronous: the run is finished and named, not handed back as a poll handle.
    assert body["dq_run_id"]
    assert "job_id" not in body and "poll_url" not in body


def test_duplicate_file_hash_returns_409_with_the_existing_batch(upload):
    """Idempotent re-upload, surfaced rather than silently doubling every volume figure."""
    first = upload(MINUTE_FIXTURE)
    assert first.status_code == 201

    second = upload(MINUTE_FIXTURE)
    assert second.status_code == 409
    assert second.json()["batch_id"] == first.json()["batch_id"]
    assert second.json()["file_hash"] == first.json()["file_hash"]


def test_duplicate_upload_loads_no_second_copy(upload, api_con):
    upload(MINUTE_FIXTURE)
    after_first = api_con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0]
    upload(MINUTE_FIXTURE)
    after_second = api_con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0]
    assert after_second == after_first


def test_preview_discloses_capability_before_any_write(client, fixture_path, api_con):
    path = fixture_path(DAILY_FIXTURE)
    with path.open("rb") as handle:
        response = client.post(
            "/v1/ingest/preview", files={"file": (path.name, handle, "text/csv")}
        )
    assert response.status_code == 200

    body = response.json()
    assert body["verdict"] == "accept"
    assert body["inferred_frequency"]["value"] == "daily"
    # The point of the step: a daily-only upload sees VWAP unavailable before commit.
    vwap = body["enables"]["vwap_15m"]
    assert vwap["available"] is False
    assert vwap["substitute_offered"] is False, "nothing may be quietly swapped in"
    assert vwap["reason"]
    # A dry run writes nothing.
    assert api_con.execute("SELECT count(*) FROM stage.ingest_batch").fetchone()[0] == 0


def test_batch_list_and_detail_agree(client, upload):
    batch_id = upload(MINUTE_FIXTURE).json()["batch_id"]

    listed = client.get("/v1/ingest/batches")
    assert listed.status_code == 200
    assert [b["batch_id"] for b in listed.json()["data"]] == [batch_id]

    detail = client.get(f"/v1/ingest/batches/{batch_id}")
    assert detail.status_code == 200
    assert detail.json() == listed.json()["data"][0]


def test_rejects_are_paginated(client, upload):
    batch_id = upload(MINUTE_FIXTURE).json()["batch_id"]
    response = client.get(f"/v1/ingest/batches/{batch_id}/rejects")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100 and body["offset"] == 0
    assert body["total"] == len(body["data"])


def test_unknown_batch_is_a_problem_document(client):
    response = client.get("/v1/ingest/batches/01900000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["code"] == "STR.UNKNOWN_BATCH"
