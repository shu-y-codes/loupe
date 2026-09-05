"""`TIM.*` — are timestamps where they should be?"""

from __future__ import annotations

from helpers import findings, set_param, source_rows


def test_out_of_order_is_judged_on_source_row(qcon, run_fixture):
    """The claim is about the order the file presented its rows in."""
    _, result = run_fixture("tim_out_of_order.csv")
    rows = findings(qcon, result.run_id, "TIM.OUT_OF_ORDER")

    assert len(rows) == 1
    assert source_rows(qcon, [rows[0]["record_id"]]) == [3]
    assert rows[0]["severity"] == "warning"


def test_future_timestamp_is_compared_against_ingest_time(qcon, run_fixture):
    """Against `ingested_at`, not `now()`: a later run must not retrospectively clear a file."""
    _, result = run_fixture("tim_future_timestamp.csv")
    rows = findings(qcon, result.run_id, "TIM.FUTURE_TIMESTAMP")

    assert len(rows) == 3
    assert {row["severity"] for row in rows} == {"error"}


def test_before_listing(qcon, fixture_path):
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("tim_before_listing.csv"))
    qcon.execute(
        "UPDATE ref.contract SET first_trade_date = DATE '2025-09-20' "
        "WHERE contract_id = 'ESZ25'"
    )
    result = run_rules(qcon, batch_id=batch.batch_id)
    rows = findings(qcon, result.run_id, "TIM.BEFORE_LISTING")

    assert len(rows) == 3
    assert rows[0]["details"]["first_trade_date"] == "2025-09-20"
    assert rows[0]["severity"] == "warning"


def test_after_expiry(qcon, fixture_path):
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("tim_after_expiry.csv"))
    qcon.execute(
        "UPDATE ref.contract SET last_trade_date = DATE '2025-09-10' "
        "WHERE contract_id = 'ESZ25'"
    )
    result = run_rules(qcon, batch_id=batch.batch_id)
    rows = findings(qcon, result.run_id, "TIM.AFTER_EXPIRY")

    assert len(rows) == 3
    assert rows[0]["severity"] == "error"


def test_a_null_reference_bound_is_not_a_finding(qcon, run_fixture):
    """Dates are inferred for every contract in this corpus; a null bound must not fire."""
    _, result = run_fixture("tim_before_listing.csv")
    assert findings(qcon, result.run_id, "TIM.BEFORE_LISTING") == []
    assert findings(qcon, result.run_id, "TIM.AFTER_EXPIRY") == []


def test_off_grid_uses_the_interval_recorded_on_the_batch(qcon, run_fixture):
    _, result = run_fixture("tim_off_grid.csv")
    rows = findings(qcon, result.run_id, "TIM.OFF_GRID")

    assert len(rows) == 1
    assert source_rows(qcon, [rows[0]["record_id"]]) == [3]
    assert rows[0]["details"] == {"inferred_interval": "1 minute", "interval_seconds": 60}


def test_a_daily_bar_is_on_grid(qcon, run_fixture):
    """Alignment is judged on the labelled wall clock.

    On `ts_utc` every daily row would be off-grid by the venue's UTC offset, which is a
    property of the timezone and not of the data.
    """
    _, result = run_fixture("rol_no_successor.csv")
    assert findings(qcon, result.run_id, "TIM.OFF_GRID") == []


def test_timezone_misaligned_finds_the_shifted_dead_zone(qcon, run_fixture):
    """The corpus cannot exercise this rule, so the fixture is a shifted derivative.

    Detection compares where the *silence* is: a 24-hour session is nearly uniform in
    coverage, so the one hour with no bars is the only sharp feature the histogram has.
    """
    _, result = run_fixture("tim_timezone_misaligned.csv")
    rows = findings(qcon, result.run_id, "TIM.TIMEZONE_MISALIGNED")

    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert rows[0]["details"]["expected_dead_hour_local"] == 16
    assert rows[0]["details"]["observed_dead_hour_local"] == 21
    assert rows[0]["details"]["offset_hours"] == 5


def test_timezone_misaligned_does_not_fire_on_a_correctly_labelled_file(qcon, fixture_path):
    """Move the dead zone back to 16:00 and the same shape produces nothing."""
    from loupe.data import load_file
    from loupe.quality import run_rules

    batch = load_file(qcon, fixture_path("tim_timezone_misaligned.csv"))
    qcon.execute(
        """
        UPDATE stage.market_record
           SET ts_exchange = ts_exchange - INTERVAL 5 HOUR,
               ts_utc = ts_utc - INTERVAL 5 HOUR
         WHERE batch_id = ?
        """,
        [batch.batch_id],
    )
    result = run_rules(qcon, batch_id=batch.batch_id)

    assert findings(qcon, result.run_id, "TIM.TIMEZONE_MISALIGNED") == []


def test_timezone_misaligned_declines_a_file_that_covers_too_little_of_the_clock(
    qcon, run_fixture
):
    """Coverage is a precondition, not a finding: a four-row file has no histogram."""
    _, result = run_fixture("cmp_partial_session.csv")
    assert findings(qcon, result.run_id, "TIM.TIMEZONE_MISALIGNED") == []


def test_timezone_misaligned_respects_its_seeded_minimums(qcon, run_fixture):
    set_param(qcon, "TIM.TIMEZONE_MISALIGNED", "min_records", 10_000)
    _, result = run_fixture("tim_timezone_misaligned.csv")
    assert findings(qcon, result.run_id, "TIM.TIMEZONE_MISALIGNED") == []
