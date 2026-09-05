"""`CMP.*` — is anything missing?

Two behaviours here are as important as the detections. Suppression: a session outside the
coverage window, on a holiday, or inside the roll window is not expected, so its absence is
not a finding. And refusal: without the calendar those suppressions cannot be applied, and a
completeness rule that evaluated anyway would report normal market behaviour as missing data.
"""

from __future__ import annotations

from datetime import date

from helpers import findings, set_param, source_rows

from loupe.quality import RunScope, scoped
from loupe.quality.scoring import expected_records


def test_null_field_names_the_field_and_the_row(qcon, run_fixture):
    """Slice 1 loads `null_fields.csv`; slice 2 is what turns those nulls into findings."""
    _, result = run_fixture("null_fields.csv")
    rows = findings(qcon, result.run_id, "CMP.NULL_FIELD")

    assert [row["details"]["field"] for row in rows] == ["close", "volume"]
    assert source_rows(qcon, [row["record_id"] for row in rows]) == [2, 3]
    assert {row["severity"] for row in rows} == {"error"}


def test_missing_timestamp_reports_a_run_as_one_row(qcon, run_fixture):
    """A gap is one finding with a slot count, not one finding per slot."""
    _, result = run_fixture("cmp_missing_timestamp.csv")
    rows = findings(qcon, result.run_id, "CMP.MISSING_TIMESTAMP")

    gap = [row for row in rows if row["affected_rows"] == 2]
    assert len(gap) == 1
    assert gap[0]["ts_start_utc"].strftime("%H:%M") == "14:02"  # 09:02 Chicago
    assert gap[0]["ts_end_utc"].strftime("%H:%M") == "14:03"
    assert gap[0]["details"]["missing_slots"] == 2
    assert gap[0]["severity"] == "warning"


def test_missing_timestamp_skips_halted_minutes(qcon, run_fixture):
    """ZC's 07:45-08:30 break is inside the session, so its minutes are not expected."""
    _, result = run_fixture("con_record_in_halt.csv")
    rows = findings(qcon, result.run_id, "CMP.MISSING_TIMESTAMP")

    halted = [
        row
        for row in rows
        if row["ts_start_utc"].strftime("%H:%M") <= "13:50" <= row["ts_end_utc"].strftime("%H:%M")
    ]
    assert halted == []


def test_session_missing_names_the_absent_session_and_its_window(qcon, run_fixture):
    _, result = run_fixture("cmp_session_missing.csv")
    rows = findings(qcon, result.run_id, "CMP.SESSION_MISSING")

    assert [row["trade_date"] for row in rows] == [date(2025, 9, 16)]
    assert rows[0]["severity"] == "error"
    assert rows[0]["details"]["window_basis"] == "observed"
    # Counted in records the session should have held, so an absent session is in the same
    # units as a gap inside one.
    assert rows[0]["affected_rows"] == 1380


def test_session_missing_records_a_liquidity_window_when_volume_supports_one(
    qcon, run_fixture
):
    """The window basis is recorded because a window chosen three ways is three claims."""
    set_param(qcon, "CMP.SESSION_MISSING", "volume_floor", 0)
    _, result = run_fixture("cmp_session_missing.csv")
    rows = findings(qcon, result.run_id, "CMP.SESSION_MISSING")

    assert rows[0]["details"]["window_basis"] == "liquidity"


def test_a_holiday_session_is_not_missing(qcon, run_fixture, fixture_path):
    """Suppression is a precondition of the family, not a refinement (spec §3)."""
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("cmp_session_missing.csv"))
    qcon.execute(
        "UPDATE ref.session_calendar SET is_holiday = TRUE "
        "WHERE root = 'ES' AND trade_date = DATE '2025-09-16'"
    )
    result = run_rules(qcon, batch_id=batch.batch_id)

    assert findings(qcon, result.run_id, "CMP.SESSION_MISSING") == []


def test_session_grained_rules_refuse_without_a_calendar(qcon, run_fixture, fixture_path):
    """Done-when 6: refuse to evaluate, rather than evaluate without the inputs."""
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("cmp_session_missing.csv"))
    qcon.execute("DELETE FROM ref.session_calendar")
    result = run_rules(qcon, batch_id=batch.batch_id)

    refused = {"CMP.MISSING_TIMESTAMP", "CMP.SESSION_MISSING", "CMP.PARTIAL_SESSION"}
    assert refused <= set(result.refusals)
    assert refused.isdisjoint(result.rules_evaluated)
    assert "ref.session_calendar" in result.refusals["CMP.SESSION_MISSING"]
    # Record-scope rules are unaffected: they need no calendar.
    assert "CMP.NULL_FIELD" in result.rules_evaluated


def test_session_grained_rules_refuse_when_the_root_is_unknown(qcon, fixture_path):
    """A contract with no reference row has no root, so no calendar can exist for it.

    That is a refusal, not an empty result: every one of its sessions would otherwise look
    like a session nobody expected.
    """
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("cmp_session_missing.csv"))
    qcon.execute("DELETE FROM ref.contract WHERE contract_id = 'ESZ25'")
    result = run_rules(qcon, batch_id=batch.batch_id)

    assert "no resolved root" in result.refusals["CMP.SESSION_MISSING"]


def test_a_saturday_session_has_no_calendar_row_so_completeness_refuses(qcon, run_fixture):
    """No session ever *closes* on a weekend, so the generator writes no row for one."""
    _, result = run_fixture("con_weekend_record.csv")
    assert "CMP.SESSION_MISSING" in result.refusals


def test_partial_session_reads_its_threshold_from_the_seeded_row(qcon, run_fixture):
    _, result = run_fixture("cmp_partial_session.csv")
    rows = findings(qcon, result.run_id, "CMP.PARTIAL_SESSION")

    assert len(rows) == 1
    assert rows[0]["details"]["threshold"] == 0.95
    assert rows[0]["details"]["expected_slots"] == 1380
    assert rows[0]["details"]["actual_slots"] == 4
    assert rows[0]["affected_rows"] == 1376


def test_partial_session_stops_firing_when_the_threshold_is_lowered(qcon, run_fixture):
    """Thresholds live in the row: a changed param needs no code change (done-when 2)."""
    set_param(qcon, "CMP.PARTIAL_SESSION", "threshold", 0.0)
    _, result = run_fixture("cmp_partial_session.csv")
    assert findings(qcon, result.run_id, "CMP.PARTIAL_SESSION") == []


def test_sparse_series_counts_sessions(qcon, run_fixture):
    _, result = run_fixture("cmp_sparse_series.csv")
    rows = findings(qcon, result.run_id, "CMP.SPARSE_SERIES")

    assert len(rows) == 1
    assert rows[0]["severity"] == "info"
    assert rows[0]["details"]["sessions"] == 1
    assert rows[0]["details"]["min_sessions"] == 20


def test_sparse_series_respects_a_lowered_minimum(qcon, run_fixture):
    set_param(qcon, "CMP.SPARSE_SERIES", "min_sessions", 1)
    _, result = run_fixture("cmp_sparse_series.csv")
    assert findings(qcon, result.run_id, "CMP.SPARSE_SERIES") == []


def test_the_roll_window_suppresses_completeness(qcon, run_fixture):
    """`ROL.THIN_NEAR_EXPIRY` and the suppression share one window definition.

    The fixture also shows the two suppressions agreeing rather than competing: volume
    collapses over the final ten sessions, so the liquidity window already stops before them
    and the roll window covers the same tail. Either one alone would keep those sessions out
    of the completeness denominator; between them the denominator is the 20 sessions the
    contract actually traded.
    """
    batch, _ = run_fixture("rol_thin_near_expiry.csv")

    with scoped(qcon, RunScope(batch_id=batch.batch_id)) as (inputs, _rows, _n):
        window = inputs.window("ESZ25", "daily")
        assert window.basis == "liquidity"
        assert window.end == date(2025, 11, 28)

        roll = inputs.roll_windows[("ESZ25", "daily")]
        assert (roll.start, roll.end) == (date(2025, 12, 2), date(2025, 12, 12))

        assert inputs.suppressed("ESZ25", "daily", date(2025, 12, 5)) is not None
        assert inputs.suppressed("ESZ25", "daily", date(2025, 11, 10)) is None

        assert expected_records(qcon, "ESZ25", "daily") == 20
