"""Trade dates and the generated session calendar.

A session is attributed to the date it closes. The trap this guards is that a full
CME-family session and a full calendar day are both 1,380 one-minute slots, so a count-only
check passes while every bar is in the wrong bucket.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from loupe.data.profiles import (
    CBOT_GRAIN_TWO_WINDOW,
    CME_23H,
    ICE_SINGLE_WINDOW,
    PRODUCTS,
    PRODUCTS_BY_ROOT,
)
from loupe.data.sessions import (
    generate_calendar,
    session_bounds,
    trade_date_for,
    trade_date_sql,
)

CHICAGO = ZoneInfo("America/Chicago")


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        # Sunday evening belongs to Monday's session, so it is not a weekend record.
        (datetime(2025, 9, 14, 17, 0), date(2025, 9, 15)),
        (datetime(2025, 9, 14, 23, 59), date(2025, 9, 15)),
        (datetime(2025, 9, 15, 0, 0), date(2025, 9, 15)),
        (datetime(2025, 9, 15, 15, 59), date(2025, 9, 15)),
        # 16:59 is after the close and before the next open: still the closing session.
        (datetime(2025, 9, 15, 16, 59), date(2025, 9, 15)),
        (datetime(2025, 9, 15, 17, 0), date(2025, 9, 16)),
    ],
)
def test_cme_trade_date_rolls_at_the_open(stamp, expected):
    assert trade_date_for(stamp, CME_23H) == expected


def test_ice_session_never_crosses_midnight():
    """SB runs 02:30-11:59 inside one calendar day, so the roll never applies."""
    assert not ICE_SINGLE_WINDOW.spans_midnight
    assert trade_date_for(datetime(2025, 9, 15, 9, 0), ICE_SINGLE_WINDOW) == date(2025, 9, 15)
    assert trade_date_for(datetime(2025, 9, 15, 17, 30), ICE_SINGLE_WINDOW) == date(2025, 9, 15)


def test_grain_session_rolls_at_its_own_open():
    """ZC opens at 19:00, not 17:00. The roll is a per-root property."""
    assert CBOT_GRAIN_TWO_WINDOW.spans_midnight
    assert trade_date_for(datetime(2026, 1, 5, 18, 59), CBOT_GRAIN_TWO_WINDOW) == date(2026, 1, 5)
    assert trade_date_for(datetime(2026, 1, 5, 19, 0), CBOT_GRAIN_TWO_WINDOW) == date(2026, 1, 6)


@pytest.mark.parametrize("profile", [CME_23H, ICE_SINGLE_WINDOW, CBOT_GRAIN_TWO_WINDOW])
@pytest.mark.parametrize("hour", range(0, 24, 3))
def test_sql_and_python_trade_dates_agree(con, profile, hour):
    """Two implementations of the boundary is exactly what the corpus warns about."""
    stamp = datetime(2025, 9, 15, hour, 30)
    expression = trade_date_sql(f"TIMESTAMP '{stamp.isoformat(sep=' ')}'", profile)
    from_sql = con.execute(f"SELECT {expression}").fetchone()[0]
    assert from_sql == trade_date_for(stamp, profile)


@pytest.mark.parametrize("product", PRODUCTS, ids=lambda p: p.root)
def test_expected_slots_equal_span_minus_halts(product):
    """The invariant that keeps the expected grid honest.

    A halt list holding the *inter-session* gap would silently shorten the grid; a missing
    intra-session halt would lengthen it. Both are caught here.
    """
    session = product.session
    open_minutes = session.open_local.hour * 60 + session.open_local.minute
    close_minutes = session.close_local.hour * 60 + session.close_local.minute
    span = close_minutes - open_minutes
    if session.spans_midnight:
        span += 24 * 60

    halted = 0
    for start, end in session.halt_windows:
        start_m = start.hour * 60 + start.minute
        end_m = end.hour * 60 + end.minute
        halted += (end_m - start_m) % (24 * 60)

    assert span - halted == session.expected_slots_1m


def test_cme_maintenance_break_is_not_an_intra_session_halt():
    """16:00-16:59 falls between a 17:00 open and a 16:00 close, so it is not a halt."""
    assert CME_23H.halt_windows == ()
    assert CBOT_GRAIN_TWO_WINDOW.halt_windows == ((time(7, 45), time(8, 30)),)


def test_session_bounds_open_on_the_previous_day_when_spanning_midnight():
    monday = date(2025, 9, 15)
    opened, closed = session_bounds(monday, PRODUCTS_BY_ROOT["ES"], CHICAGO)
    assert opened.astimezone(CHICAGO).date() == date(2025, 9, 14)
    assert opened.astimezone(CHICAGO).time() == time(17, 0)
    assert closed.astimezone(CHICAGO).date() == monday
    assert closed.astimezone(CHICAGO).time() == time(16, 0)


def test_calendar_skips_weekends_and_marks_full_closures():
    rows = {r.trade_date: r for r in generate_calendar("ES", date(2025, 12, 22), date(2026, 1, 2))}
    assert date(2025, 12, 27) not in rows  # Saturday
    assert rows[date(2025, 12, 25)].is_holiday
    assert rows[date(2025, 12, 25)].expected_slots_1m == 0
    assert rows[date(2026, 1, 1)].is_holiday
    assert rows[date(2025, 12, 24)].is_early_close
    # An early close has a session; we do not know its truncated grid, so the denominator
    # is null rather than a number we made up.
    assert rows[date(2025, 12, 24)].expected_slots_1m is None
    assert rows[date(2025, 12, 23)].expected_slots_1m == 1380


def test_calendar_carries_dst_through_the_transition():
    """The session length is constant across the DST change; the UTC offset is not."""
    # US clocks go back on 2025-11-02, so a 31 October session opens in CDT and a
    # 7 November one opens in CST.
    rows = {r.trade_date: r for r in generate_calendar("ES", date(2025, 10, 31), date(2025, 11, 7))}
    before = rows[date(2025, 10, 31)]
    after = rows[date(2025, 11, 7)]
    for row in (before, after):
        span = (row.session_close_utc - row.session_open_utc).total_seconds() / 60
        assert span == 1380
    assert before.session_open_utc.hour != after.session_open_utc.hour


def test_grain_calendar_carries_its_halt():
    rows = {r.trade_date: r for r in generate_calendar("ZC", date(2026, 1, 5), date(2026, 1, 7))}
    halts = rows[date(2026, 1, 6)].halt_windows_utc
    assert len(halts) == 1
    start = datetime.fromisoformat(halts[0]["start_utc"]).astimezone(CHICAGO)
    assert start.time() == time(7, 45)
    assert start.date() == date(2026, 1, 6)
