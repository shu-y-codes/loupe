"""Rolling 15-minute VWAP: the frame, the partition, and the honest null."""

from __future__ import annotations

from datetime import date

import pytest

from loupe.insights import compare_vwap, published_vwap, vwap_15m


def _at(points, hour, minute):
    matches = [p for p in points if p.ts_utc.hour == hour and p.ts_utc.minute == minute]
    assert len(matches) == 1, f"no single point at {hour:02d}:{minute:02d}"
    return matches[0]


def test_the_window_is_a_time_range_not_a_row_count(load_and_build, icon):
    """The spec's four-row worked example (§4.6), committed as a test.

    A `ROWS BETWEEN 14 PRECEDING` frame would hold all four records at 09:20. The `RANGE`
    frame holds two, because 09:00 is more than fifteen minutes old — and that difference is
    the whole point: a row-count frame stretches over gaps, silently, exactly where the data
    is worst.
    """
    load_and_build("insights_vwap_window.csv")
    points = vwap_15m(icon)

    # ts_utc is 14:00Z for 09:00 Chicago; assert on the ordering rather than the offset.
    # 09:00 -> 1; 09:10 sees 09:00; 09:20 sees 09:10 only (09:00 has aged out); 09:25 sees
    # 09:10, 09:20 and itself, because fifteen minutes old is still inside.
    assert [p.window_records for p in points] == [1, 2, 2, 3]


def test_a_record_exactly_fifteen_minutes_old_is_still_inside(load_and_build, icon):
    """`[t - 15 min, t]`, inclusive at both ends."""
    load_and_build("insights_vwap_window.csv")
    points = vwap_15m(icon)

    # At 09:25 the frame is [09:10, 09:25]. The 09:10 record is exactly fifteen minutes old
    # and is included; 09:00 is sixteen and is not. An exclusive frame would hold two.
    assert points[3].window_records == 3
    assert points[2].window_records == 2


def test_zero_window_volume_is_null_and_never_zero(load_and_build, icon):
    """Not 0, not the previous value, not interpolated. The chart shows a break in the line."""
    load_and_build("insights_vwap_zero_volume.csv")
    points = vwap_15m(icon)

    assert len(points) == 3
    assert all(p.vwap_15m is None for p in points)
    assert all(p.window_volume == 0 for p in points)


def test_a_zero_volume_record_joins_the_window_without_moving_the_number(load_and_build, icon):
    """It contributes nothing to either side of the ratio, so the value is carried, not lost."""
    load_and_build("insights_vwap_window.csv")
    points = vwap_15m(icon)

    assert points[3].window_volume == points[2].window_volume
    assert points[3].window_records == points[2].window_records + 1


def test_the_window_never_spans_two_sessions(load_and_build, icon):
    """Without `trade_date` in the partition, the first window after the maintenance break
    reaches back through it and mixes in stale pre-break prices."""
    load_and_build("session_roll_boundary.csv")
    points = vwap_15m(icon)

    first_of_new_session = [p for p in points if p.trade_date == date(2025, 9, 16)][0]
    assert first_of_new_session.window_records == 1


def test_warm_up_is_marked_rather_than_hidden(load_and_build, icon):
    """Nulling it loses information; presenting it unmarked overstates confidence."""
    load_and_build("insights_vwap_window.csv")
    points = vwap_15m(icon)

    assert [p.is_warmup for p in points] == [True, True, False, False]


def test_the_price_basis_is_a_parameter_and_changes_the_line(load_and_build, icon):
    """Typical price by default; `close` alone discards the intra-bar range.

    Run against a fixture whose bars are *asymmetric*: where high and low sit equidistant
    from the close, `(H+L+C)/3` equals the close and the two bases agree by construction —
    true of the §4.6 worked example, and a trap for a test that used it here.
    """
    load_and_build("session_roll_boundary.csv")
    typical = vwap_15m(icon, price_basis="typical")
    close = vwap_15m(icon, price_basis="close")

    assert typical[0].vwap_15m == pytest.approx((6601.00 + 6600.00 + 6600.75) / 3)
    assert close[0].vwap_15m == pytest.approx(6600.75)
    assert [p.vwap_15m for p in typical] != [p.vwap_15m for p in close]


def test_an_unknown_basis_is_refused_rather_than_interpolated(load_and_build, icon):
    """These arrive from a query string in slice 4; a lookup is what keeps that safe."""
    load_and_build("insights_vwap_window.csv")

    with pytest.raises(ValueError):
        vwap_15m(icon, basis="'; DROP TABLE stage.market_record; --")
    with pytest.raises(ValueError):
        vwap_15m(icon, price_basis="mid")


def test_the_shipped_view_is_the_default_published_line(load_and_build, icon):
    """`mart.vwap_15m` is typical price on the clean basis; the helper must agree with it."""
    load_and_build("insights_vwap_window.csv")
    view = icon.execute(
        "SELECT contract_id, trade_date, ts_utc, vwap_15m, window_volume, window_records,"
        " is_warmup FROM mart.vwap_15m ORDER BY ts_utc"
    ).fetchall()
    helper = vwap_15m(icon, basis="clean", price_basis="typical")

    assert view == [
        (p.contract_id, p.trade_date, p.ts_utc, p.vwap_15m, p.window_volume,
         p.window_records, p.is_warmup)
        for p in helper
    ]


def test_a_daily_only_corpus_is_refused_rather_than_empty(load_and_build, icon):
    """A daily row cannot contribute to a rolling fifteen-minute window.

    Slice 3 recorded that as `unavailable` for want of a better state. Slice 4 gave it one:
    "no rows came back" and "no rows *can* come back at this grain" are different answers
    and different HTTP responses (`plans/04-api.md` done-when 7), so this asserts the
    refusal and, explicitly, that it is *not* reported as an empty series.
    """
    load_and_build("con_derived_bar_invalid_vendor.csv")
    series = published_vwap(icon, contract_id="CLZ25")

    assert series.rows == ()
    assert series.frequency_unavailable
    assert not series.unavailable
    assert not series.blocked
    assert series.unsupported.frequencies_available == ("daily",)


def test_compare_vwap_aligns_the_two_bases(load_and_build, icon):
    load_and_build("insights_vwap_window.csv")
    deltas = compare_vwap(icon)

    assert len(deltas) == 4
    assert all(d.delta == 0 for d in deltas)
    assert not any(d.differs for d in deltas)
