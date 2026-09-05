"""Daily OHLCV bars: the aggregation, the tie-break, and the provenance that travels with it."""

from __future__ import annotations

from datetime import date

import pytest

from loupe.insights import build_bars, compare_bars, read_bars


def _bar(icon, contract_id="ESZ25", *, trade_date=None, basis="clean", source="derived"):
    bars = read_bars(
        icon, contract_id=contract_id, trade_date=trade_date, basis=basis, source=source
    )
    assert len(bars) == 1, f"expected one bar, got {len(bars)}"
    return bars[0]


# ------------------------------------------------------------------- the aggregation itself


def test_open_and_close_are_positional_high_and_low_extremal(load_and_build, icon):
    """`min(open)` and `max(close)` are the canonical bug (§3.1)."""
    load_and_build("insights_vwap_window.csv")
    bar = _bar(icon)

    assert bar.open == 6600.00  # first record's open, not the lowest open
    assert bar.close == 6630.00  # last record's close, not the highest close
    assert bar.high == 6632.00
    assert bar.low == 6598.00
    assert bar.volume == 600


def test_a_tie_on_timestamp_breaks_on_source_row(load_and_build, icon):
    """Two records share the earliest timestamp; the file's order decides, not the planner."""
    load_and_build("insights_bar_tie_break.csv")
    bar = _bar(icon)

    assert bar.open == 6600.00
    assert bar.record_count == 3


def test_a_null_at_the_edge_stays_null(load_and_build, icon):
    """DuckDB's arg_min/arg_max skip null *values*, which is not the definition.

    §3.1 asks for the value of the earliest record, and that value may legitimately be null.
    A writer that let arg_min skip it would report the second record's open as the session's
    open — a plausible number with no basis in the data.
    """
    load_and_build("insights_bar_null_edges.csv")
    bar = _bar(icon)

    assert bar.open is None
    assert bar.close is None
    assert bar.high == 6602.00


def test_the_shipped_form_agrees_with_the_row_number_reference(load_and_build, icon):
    """§3.2 keeps the `row_number()` form as the test reference for the compact one."""
    load_and_build("insights_bar_null_edges.csv")
    reference = icon.execute(
        """
        WITH ordered AS (
          SELECT *,
            row_number() OVER (PARTITION BY contract_id, trade_date
                               ORDER BY ts_utc ASC,  source_row ASC)  AS rn_first,
            row_number() OVER (PARTITION BY contract_id, trade_date
                               ORDER BY ts_utc DESC, source_row DESC) AS rn_last
          FROM dq.market_record_clean
          WHERE frequency = 'minute'
        )
        SELECT contract_id, trade_date,
               max(CASE WHEN rn_first = 1 THEN open  END) AS open,
               max(high) AS high, min(low) AS low,
               max(CASE WHEN rn_last  = 1 THEN close END) AS close,
               sum(volume) AS volume
        FROM ordered GROUP BY 1, 2
        """
    ).fetchall()

    bar = _bar(icon)
    assert reference == [
        (bar.contract_id, bar.trade_date, bar.open, bar.high, bar.low, bar.close, bar.volume)
    ]


def test_a_skipped_null_volume_is_reported_not_silent(load_and_build, icon):
    """`sum()` skips nulls, so the count is what stops the total being quietly short."""
    load_and_build("null_fields.csv")
    bar = _bar(icon)

    assert bar.volume_null_count == 1
    assert bar.volume == 280  # 120 + 90 + 70, with the null skipped


def test_open_interest_is_the_last_reported_never_the_sum(load_and_build, icon):
    """It is a stock, not a flow: adding the minute readings produces a meaningless number."""
    load_and_build("insights_vwap_window.csv")
    icon.execute(
        "UPDATE stage.market_record SET open_interest = 500 WHERE ts_exchange = "
        "TIMESTAMP '2025-09-15 09:00:00'"
    )
    icon.execute(
        "UPDATE stage.market_record SET open_interest = 900 WHERE ts_exchange = "
        "TIMESTAMP '2025-09-15 09:20:00'"
    )
    build_bars(icon)

    assert _bar(icon).open_interest == 900


# ------------------------------------------------------------------------ session membership


def test_the_session_boundary_not_the_calendar_date_groups_the_bar(load_and_build, icon):
    """The 1,380 coincidence: a calendar-date grouping gets the same count and other bars.

    Asserting on membership rather than on counts is the only defence, so this asserts the
    Sunday-evening records landed in the *next* session (§2.2.1).
    """
    load_and_build("session_roll_boundary.csv")
    bars = read_bars(icon, contract_id="ESZ25")

    assert [b.trade_date for b in bars] == [date(2025, 9, 15), date(2025, 9, 16)]
    # 17:00 and 17:01 on the 15th belong to the 16th's session, and carry its close.
    assert bars[0].close == 6601.50  # the 16:59 record, last before the roll
    assert bars[1].open == 6601.50  # the 17:00 record, first after it
    assert bars[1].close == 6602.25


def test_every_bar_records_the_boundary_that_produced_it(load_and_build, icon):
    """Not a bare "CME": two boundaries yield bars with identical counts and other prices."""
    load_and_build("session_roll_boundary.csv")
    bar = _bar(icon, trade_date=date(2025, 9, 16))

    assert bar.session_boundary.startswith("CME:ES:")
    assert "2025-09-15T22:00:00Z/2025-09-16T21:00:00Z" in bar.session_boundary


# -------------------------------------------------------------------------------- provenance


def test_a_derived_bar_carries_its_grid_and_a_vendor_bar_does_not(load_and_build, icon):
    """One supplied daily row is not a sample of 1,380 one-minute slots."""
    load_and_build("insights_vwap_window.csv")
    derived = _bar(icon)

    assert derived.source == "derived"
    assert derived.source_frequency == "minute"
    assert derived.close_convention == "last_trade"
    assert derived.expected_count == 1380
    assert derived.completeness_pct == pytest.approx(4 / 1380 * 100)


def test_vendor_daily_rows_are_projected_with_their_own_convention(load_and_build, icon):
    load_and_build("con_derived_bar_invalid_vendor.csv")
    bars = read_bars(icon, contract_id="CLZ25", source="vendor")

    assert len(bars) == 3
    assert {b.source_frequency for b in bars} == {"daily"}
    assert {b.close_convention for b in bars} == {"settlement"}
    assert all(b.expected_count is None and b.completeness_pct is None for b in bars)
    assert all(b.session_boundary.endswith(":vendor-date-column") for b in bars)


def test_bars_are_materialised_under_both_bases(load_and_build, icon):
    _, report = load_and_build("insights_vwap_window.csv")

    assert report.count("raw", "derived") == 1
    assert report.count("clean", "derived") == 1
    assert len(read_bars(icon, basis="raw")) == 1


def test_rebuilding_replaces_rather_than_duplicates(load_and_build, icon):
    """The bar table is a projection: a rebuild after cleaning must not double it."""
    load_and_build("insights_vwap_window.csv")
    build_bars(icon)
    build_bars(icon)

    assert len(read_bars(icon)) == 1


def test_a_session_with_no_records_gets_no_row(load_and_build, icon):
    """A zero-filled bar would assert a flat session; `CMP.SESSION_MISSING` reports absence."""
    load_and_build("insights_vwap_window.csv")

    assert read_bars(icon, trade_date=date(2025, 9, 16)) == []


def test_compare_bars_pairs_the_two_bases(load_and_build, icon):
    load_and_build("insights_vwap_window.csv")
    deltas = compare_bars(icon)

    assert len(deltas) == 1
    assert deltas[0].raw is not None and deltas[0].clean is not None
    assert not deltas[0].differs
