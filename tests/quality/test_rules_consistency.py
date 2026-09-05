"""`CON.*` — do values agree with each other, and with the calendar?"""

from __future__ import annotations

from datetime import date

import pytest
from helpers import findings, set_param, source_rows


def test_high_below_low_is_reported_once(qcon, run_fixture):
    _, result = run_fixture("con_high_lt_low.csv")
    rows = findings(qcon, result.run_id, "CON.HIGH_LT_LOW")

    assert len(rows) == 1
    assert source_rows(qcon, [rows[0]["record_id"]]) == [2]
    assert rows[0]["severity"] == "error"


def test_an_inverted_range_stands_the_other_range_tests_down(qcon, run_fixture):
    """Where high < low, "inside the range" means nothing.

    Reporting all three would turn one defect into three findings for the same record and
    make a worklist ordered by affected rows read as if the row were three times as broken.
    """
    _, result = run_fixture("con_high_lt_low.csv")
    assert findings(qcon, result.run_id, "CON.OPEN_OUT_OF_RANGE") == []
    assert findings(qcon, result.run_id, "CON.CLOSE_OUT_OF_RANGE") == []


def test_open_outside_the_range(qcon, run_fixture):
    _, result = run_fixture("con_open_out_of_range.csv")
    rows = findings(qcon, result.run_id, "CON.OPEN_OUT_OF_RANGE")

    assert len(rows) == 1
    assert rows[0]["details"]["value"] == pytest.approx(6605.0)
    assert rows[0]["details"]["high"] == pytest.approx(6602.0)


def test_close_outside_the_range(qcon, run_fixture):
    _, result = run_fixture("con_close_out_of_range.csv")
    rows = findings(qcon, result.run_id, "CON.CLOSE_OUT_OF_RANGE")

    assert len(rows) == 1
    assert rows[0]["details"]["value"] == pytest.approx(6599.0)
    assert rows[0]["details"]["low"] == pytest.approx(6600.5)


def test_weekend_record_fires_on_the_derived_session_date(qcon, run_fixture):
    """Friday evening is after the week's close, so the 17:00 roll lands on Saturday."""
    _, result = run_fixture("con_weekend_record.csv")
    rows = findings(qcon, result.run_id, "CON.WEEKEND_RECORD")

    assert len(rows) == 2
    assert {row["trade_date"] for row in rows} == {date(2025, 9, 20)}
    assert {row["details"]["weekday"] for row in rows} == {"Saturday"}


def test_a_sunday_evening_bar_is_not_a_weekend_record(qcon, run_fixture):
    """The negative case, and the reason the rule refuses a vendor date column.

    On the vendor's own `trading_date` this corpus yields 179,934 weekend records, every one
    of them a Sunday-evening CME bar belonging to Monday's session. On the derived date the
    count is zero (`specs/sample-corpus.md` §7.1).
    """
    _, result = run_fixture("weekend_sunday_evening.csv")
    assert findings(qcon, result.run_id, "CON.WEEKEND_RECORD") == []

    dates = qcon.execute("SELECT DISTINCT trade_date FROM stage.market_record").fetchall()
    assert dates == [(date(2025, 9, 15),)]


def test_record_in_halt_uses_the_intra_session_break(qcon, run_fixture):
    """ZC's session is two blocks, so it carries one halt; ES's is one block and carries none."""
    _, result = run_fixture("con_record_in_halt.csv")
    rows = findings(qcon, result.run_id, "CON.RECORD_IN_HALT")

    assert source_rows(qcon, [row["record_id"] for row in rows]) == [2, 3, 4]
    assert {row["severity"] for row in rows} == {"warning"}


def test_the_maintenance_break_between_sessions_is_not_a_halt(qcon, run_fixture):
    """The CME 16:00-17:00 break falls *between* sessions, so ES has no halt windows."""
    _, result = run_fixture("session_roll_boundary.csv")
    assert findings(qcon, result.run_id, "CON.RECORD_IN_HALT") == []


def test_record_on_holiday(qcon, run_fixture):
    """Only New Year's Day and Christmas Day are full closures in this corpus."""
    _, result = run_fixture("con_record_on_holiday.csv")
    rows = findings(qcon, result.run_id, "CON.RECORD_ON_HOLIDAY")

    assert len(rows) == 3
    assert {row["trade_date"] for row in rows} == {date(2025, 12, 25)}


def test_stale_repeat_reports_a_run_as_one_finding(qcon, run_fixture):
    _, result = run_fixture("con_stale_repeat.csv")
    rows = findings(qcon, result.run_id, "CON.STALE_REPEAT")

    assert len(rows) == 1
    assert rows[0]["affected_rows"] == 32
    assert rows[0]["details"]["threshold_n"] == 30


def test_stale_repeat_reads_a_per_root_threshold(qcon, run_fixture):
    """`n` is not global: at n = 10 the corpus fires 14,830 times and 13,285 are SR3."""
    set_param(qcon, "CON.STALE_REPEAT", "n_by_root", {"ES": 40})
    _, result = run_fixture("con_stale_repeat.csv")
    assert findings(qcon, result.run_id, "CON.STALE_REPEAT") == []


def test_price_jump_is_informational(qcon, run_fixture):
    _, result = run_fixture("con_price_jump.csv")
    rows = findings(qcon, result.run_id, "CON.PRICE_JUMP")

    assert len(rows) == 1
    assert rows[0]["severity"] == "info"
    assert rows[0]["details"]["log_return"] == pytest.approx(0.0588, abs=1e-3)
    assert rows[0]["details"]["threshold"] == 0.05


# ------------------------------------------------------- CON.DERIVED_BAR_INVALID (slice 3)


def test_derived_bar_invalid_refuses_before_any_bars_exist(qcon, run_fixture):
    """No bars is not the same as no violations, and the runner must not conflate them."""
    _, result = run_fixture("con_derived_bar_invalid.csv", clean=False)

    assert "CON.DERIVED_BAR_INVALID" in result.refusals
    assert "build_bars" in result.refusals["CON.DERIVED_BAR_INVALID"]
    assert findings(qcon, result.run_id, "CON.DERIVED_BAR_INVALID") == []


def test_a_derived_bar_that_breaks_its_invariants_is_critical(qcon, run_fixture_with_bars):
    """The last record's close sits above the session high, so the bar's close does too."""
    _, result = run_fixture_with_bars("con_derived_bar_invalid.csv", clean=False)
    rows = findings(qcon, result.run_id, "CON.DERIVED_BAR_INVALID")

    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert rows[0]["contract_id"] == "ESZ25"
    assert rows[0]["trade_date"] == date(2025, 9, 15)
    assert rows[0]["details"]["source"] == "derived"
    assert "escaped record-level validation" in rows[0]["details"]["explanation"]


def test_a_vendor_bar_that_breaks_them_is_only_a_warning(qcon, run_fixture_with_bars):
    """A settlement close is not obliged to sit inside the traded range.

    Without the split, ingesting this corpus's daily config raises 43 critical findings on
    arrival — accurate about the arithmetic, wrong about what the data means
    (`specs/sample-corpus.md` §7.5).
    """
    _, result = run_fixture_with_bars("con_derived_bar_invalid_vendor.csv", clean=False)
    rows = findings(qcon, result.run_id, "CON.DERIVED_BAR_INVALID")

    assert len(rows) == 1
    assert rows[0]["severity"] == "warning"
    assert rows[0]["details"]["source"] == "vendor"
    assert "settlement" in rows[0]["details"]["explanation"]


def test_the_vendor_severity_comes_from_the_row_not_a_branch(qcon, run_fixture_with_bars):
    """Both severities are seeded, so a deployment can move either without a code change."""
    set_param(qcon, "CON.DERIVED_BAR_INVALID", "vendor_severity", "info")
    _, result = run_fixture_with_bars("con_derived_bar_invalid_vendor.csv", clean=False)
    rows = findings(qcon, result.run_id, "CON.DERIVED_BAR_INVALID")

    assert [row["severity"] for row in rows] == ["info"]


def test_cleaning_the_bad_record_leaves_the_bar_valid(qcon, run_fixture_with_bars):
    """A defect the record-scope rules caught is validation working, not a defect escaping."""
    _, result = run_fixture_with_bars("con_derived_bar_invalid.csv", clean=True)

    assert findings(qcon, result.run_id, "CON.DERIVED_BAR_INVALID") == []
    assert findings(qcon, result.run_id, "CON.CLOSE_OUT_OF_RANGE") != []
