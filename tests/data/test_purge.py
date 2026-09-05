"""The purge cascade as a unit (`plans/04-api.md` done-when 5).

`tests/api/test_purge.py` asserts the same cascade through the route. These tests cover what
the route cannot reach: which findings a purge is entitled to delete, and which it must
leave alone because they are statements about another batch's records too.
"""

from __future__ import annotations

import pytest

from loupe.data import BatchAlreadyPurged, BatchNotFound, load_file, purge_batch
from loupe.insights import build_bars
from loupe.quality import run_rules, seed_quality

MINUTE_FIXTURE = "insights_vwap_window.csv"
OTHER_FIXTURE = "cmp_missing_timestamp.csv"


@pytest.fixture
def pcon(con):
    seed_quality(con)
    return con


def test_purge_reports_what_it_removed(pcon, fixture_path):
    batch = load_file(pcon, fixture_path(MINUTE_FIXTURE))
    run_rules(pcon, batch_id=batch.batch_id)
    build_bars(pcon)

    result = purge_batch(pcon, batch.batch_id)

    assert result.batch_id == batch.batch_id
    assert result.records_deleted == batch.rows_accepted
    assert result.sessions_affected > 0
    assert result.total_deleted >= result.records_deleted


def test_purge_drops_the_bars_over_sessions_it_fed(pcon, fixture_path):
    """A bar is a statement about a record set that no longer exists."""
    batch = load_file(pcon, fixture_path(MINUTE_FIXTURE))
    build_bars(pcon)
    assert pcon.execute("SELECT count(*) FROM mart.bar_daily").fetchone()[0] > 0

    result = purge_batch(pcon, batch.batch_id)

    assert result.bars_deleted > 0
    assert pcon.execute("SELECT count(*) FROM mart.bar_daily").fetchone()[0] == 0


def test_purge_deletes_findings_from_runs_over_that_batch(pcon, fixture_path):
    batch = load_file(pcon, fixture_path("con_close_out_of_range.csv"))
    run = run_rules(pcon, batch_id=batch.batch_id)
    assert run.findings_count > 0

    purge_batch(pcon, batch.batch_id)

    remaining = pcon.execute(
        "SELECT count(*) FROM dq.dq_finding WHERE run_id = ?", [run.run_id]
    ).fetchone()[0]
    assert remaining == 0


def test_purge_leaves_another_batch_alone(pcon, fixture_path):
    keep = load_file(pcon, fixture_path(OTHER_FIXTURE))
    drop = load_file(pcon, fixture_path(MINUTE_FIXTURE))
    run_rules(pcon, batch_id=keep.batch_id)
    kept_findings = pcon.execute("SELECT count(*) FROM dq.dq_finding").fetchone()[0]

    purge_batch(pcon, drop.batch_id)

    assert (
        pcon.execute(
            "SELECT count(*) FROM stage.market_record WHERE batch_id = ?", [keep.batch_id]
        ).fetchone()[0]
        == keep.rows_accepted
    )
    assert pcon.execute("SELECT count(*) FROM dq.dq_finding").fetchone()[0] == kept_findings


def test_purge_is_a_soft_delete(pcon, fixture_path):
    batch = load_file(pcon, fixture_path(MINUTE_FIXTURE))
    purge_batch(pcon, batch.batch_id)

    row = pcon.execute(
        "SELECT status, file_hash FROM stage.ingest_batch WHERE batch_id = ?",
        [batch.batch_id],
    ).fetchone()
    assert row[0] == "purged"
    assert row[1] == batch.file_hash, "the idempotency key survives the purge"


def test_unknown_and_repeated_purges_raise(pcon, fixture_path):
    with pytest.raises(BatchNotFound):
        purge_batch(pcon, "01900000-0000-0000-0000-000000000000")

    batch = load_file(pcon, fixture_path(MINUTE_FIXTURE))
    purge_batch(pcon, batch.batch_id)
    with pytest.raises(BatchAlreadyPurged):
        purge_batch(pcon, batch.batch_id)


def test_purging_a_batch_with_no_records_is_not_an_error(pcon, fixture_path):
    """A failed load can leave a batch row with nothing under it. Purge still applies."""
    batch = load_file(pcon, fixture_path(MINUTE_FIXTURE))
    pcon.execute("DELETE FROM stage.market_record WHERE batch_id = ?", [batch.batch_id])

    result = purge_batch(pcon, batch.batch_id)
    assert result.records_deleted == 0
    assert result.bars_deleted == 0
    assert result.sessions_affected == 0
