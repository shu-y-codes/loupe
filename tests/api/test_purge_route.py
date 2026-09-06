"""Purge cascade tests (`plans/04-api.md` done-when 5).

The cascade is `loupe.data.purge`'s to own, so these assert the *effect* through the route:
the batch's rows leave every downstream table, an unrelated batch is untouched, and the
batch row itself survives as `purged` so ingest history stays intact.
"""

from __future__ import annotations

import pytest

MINUTE_FIXTURE = "insights_vwap_window.csv"
OTHER_MINUTE_FIXTURE = "cmp_missing_timestamp.csv"


def counts(con, batch_id: str) -> dict[str, int]:
    """Everything downstream of one batch, counted in one place."""
    return {
        "records": con.execute(
            "SELECT count(*) FROM stage.market_record WHERE batch_id = ?", [batch_id]
        ).fetchone()[0],
        "rejects": con.execute(
            "SELECT count(*) FROM stage.record_reject WHERE batch_id = ?", [batch_id]
        ).fetchone()[0],
        "findings": con.execute(
            "SELECT count(*) FROM dq.dq_finding f "
            "WHERE f.run_id IN (SELECT run_id FROM dq.dq_run WHERE batch_id = ?)",
            [batch_id],
        ).fetchone()[0],
    }


@pytest.fixture
def loaded(upload):
    """One batch, validated — ingest materialises derived bars."""
    return upload(MINUTE_FIXTURE).json()["batch_id"]


def test_purge_removes_records_rejects_findings_and_bars(client, api_con, loaded):
    before = counts(api_con, loaded)
    assert before["records"] > 0, "fixture must load rows for the test to mean anything"
    bars_before = api_con.execute("SELECT count(*) FROM mart.bar_daily").fetchone()[0]
    assert bars_before > 0

    response = client.delete(f"/v1/ingest/batches/{loaded}")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "purged"
    assert body["records_deleted"] == before["records"]
    assert body["bars_deleted"] > 0

    after = counts(api_con, loaded)
    assert after == {"records": 0, "rejects": 0, "findings": 0}
    assert api_con.execute("SELECT count(*) FROM mart.bar_daily").fetchone()[0] == 0


def test_purge_is_a_soft_delete(client, api_con, loaded):
    client.delete(f"/v1/ingest/batches/{loaded}")
    status = api_con.execute(
        "SELECT status FROM stage.ingest_batch WHERE batch_id = ?", [loaded]
    ).fetchone()
    assert status is not None, "the batch row must survive: ingest history stays intact"
    assert status[0] == "purged"


def test_purged_batch_is_hidden_from_the_list_but_retrievable(client, loaded):
    client.delete(f"/v1/ingest/batches/{loaded}")
    assert client.get("/v1/ingest/batches").json()["total"] == 0
    assert client.get("/v1/ingest/batches", params={"include_purged": True}).json()["total"] == 1
    assert client.get(f"/v1/ingest/batches/{loaded}").status_code == 200


def test_purge_leaves_an_unrelated_batch_intact(client, api_con, upload):
    keep = upload(OTHER_MINUTE_FIXTURE).json()["batch_id"]
    drop = upload(MINUTE_FIXTURE).json()["batch_id"]
    kept_before = counts(api_con, keep)
    assert kept_before["records"] > 0

    client.delete(f"/v1/ingest/batches/{drop}")

    assert counts(api_con, keep) == kept_before
    assert (
        api_con.execute(
            "SELECT status FROM stage.ingest_batch WHERE batch_id = ?", [keep]
        ).fetchone()[0]
        != "purged"
    )


def test_second_purge_is_refused_rather_than_reported_as_a_second_delete(client, loaded):
    assert client.delete(f"/v1/ingest/batches/{loaded}").status_code == 200
    repeat = client.delete(f"/v1/ingest/batches/{loaded}")
    assert repeat.status_code == 409
    assert repeat.json()["code"] == "STR.ALREADY_PURGED"


def test_purging_an_unknown_batch_is_404(client):
    response = client.delete("/v1/ingest/batches/01900000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "STR.UNKNOWN_BATCH"


def test_purged_bytes_can_be_uploaded_again(client, upload, loaded):
    """The batch row survives, so its `file_hash` still exists — but the rows are gone.

    A re-upload of purged bytes is still recognised as the duplicate it is. That is the
    trade-off soft delete makes, and it is asserted here rather than left to be discovered.
    """
    client.delete(f"/v1/ingest/batches/{loaded}")
    again = upload("insights_vwap_window.csv")
    assert again.status_code == 409
