"""`ROL.*` — the rules that exist to reduce noise rather than to report defects."""

from __future__ import annotations

from datetime import date

from helpers import findings, set_param


def test_thin_near_expiry_reports_the_window_it_suppresses(qcon, run_fixture):
    _, result = run_fixture("rol_thin_near_expiry.csv")
    rows = findings(qcon, result.run_id, "ROL.THIN_NEAR_EXPIRY")

    assert len(rows) == 1
    assert rows[0]["severity"] == "info"
    assert rows[0]["details"]["window_start"] == "2025-12-02"
    assert rows[0]["details"]["window_end"] == "2025-12-12"
    assert rows[0]["details"]["median_session_volume_inside"] == 10.0
    assert rows[0]["details"]["median_session_volume_before"] == 100000.0
    assert rows[0]["details"]["expiry_basis"] == "observed"


def test_thin_near_expiry_uses_the_listed_expiry_when_there_is_one(qcon, fixture_path):
    """Dates are inferred here, so which expiry was used is recorded rather than assumed."""
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("rol_thin_near_expiry.csv"))
    qcon.execute(
        "UPDATE ref.contract SET last_trade_date = DATE '2025-12-15' "
        "WHERE contract_id = 'ESZ25'"
    )
    result = run_rules(qcon, batch_id=batch.batch_id)
    rows = findings(qcon, result.run_id, "ROL.THIN_NEAR_EXPIRY")

    assert rows[0]["details"]["expiry_basis"] == "listed"
    assert rows[0]["details"]["window_end"] == "2025-12-15"


def test_a_series_with_no_volume_collapse_produces_no_roll_window(qcon, run_fixture):
    _, result = run_fixture("rol_no_successor.csv")
    assert findings(qcon, result.run_id, "ROL.THIN_NEAR_EXPIRY") == []


def test_thin_near_expiry_reads_its_collapse_ratio_from_the_row(qcon, run_fixture):
    set_param(qcon, "ROL.THIN_NEAR_EXPIRY", "collapse_ratio", 0.0)
    _, result = run_fixture("rol_thin_near_expiry.csv")
    assert findings(qcon, result.run_id, "ROL.THIN_NEAR_EXPIRY") == []


def test_no_successor_names_only_the_contract_at_the_end_of_the_chain(qcon, run_fixture):
    """ESZ25 rolls into ESH26; ESH26 has nowhere to go, so only it is reported."""
    _, result = run_fixture("rol_no_successor.csv")
    rows = findings(qcon, result.run_id, "ROL.NO_SUCCESSOR")

    assert [row["contract_id"] for row in rows] == ["ESH26"]
    assert rows[0]["severity"] == "info"
    assert rows[0]["trade_date"] == date(2025, 11, 10)
