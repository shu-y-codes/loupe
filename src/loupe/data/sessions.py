"""Sessions and trade dates.

A "day" is a trading session, not a calendar date, and the session is per root (locked
decision 3). The session is attributed to the date it **closes**, so for a CME-family root
opening at 17:00 local:

    local_time <  17:00  ->  that calendar date
    local_time >= 17:00  ->  the next calendar date

A naive `GROUP BY date(timestamp)` misattributes every overnight bar while producing exactly
the right expected *count* for a CME-family session — 1,380 slots either way — so a
count-only check passes with entirely wrong membership. That coincidence is the reason this
module exists rather than a one-line date cast at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .profiles import PRODUCTS_BY_ROOT, Product, SessionProfile, holiday_index


def trade_date_for(ts_exchange: datetime, session: SessionProfile) -> date:
    """The session date of a wall-clock timestamp under one session profile."""
    if session.spans_midnight and ts_exchange.time() >= session.open_local:
        return ts_exchange.date() + timedelta(days=1)
    return ts_exchange.date()


def trade_date_sql(ts_expr: str, session: SessionProfile) -> str:
    """The same rule as SQL, for the ingest path.

    Ingest assigns a trade date to millions of rows, so it runs in DuckDB rather than in a
    Python loop. Both forms are exercised against each other in `tests/data/test_sessions.py`,
    because two implementations of the boundary is exactly the situation the corpus warns
    about.

    A session that stays inside one calendar day never rolls, so SB gets a plain date cast
    rather than a boundary that would push every afternoon bar into tomorrow.
    """
    if not session.spans_midnight:
        return f"CAST({ts_expr} AS DATE)"
    return roll_sql(ts_expr, f"TIME '{session.open_local.strftime('%H:%M:%S')}'")


def roll_sql(ts_expr: str, boundary_expr: str) -> str:
    """Roll onto the next calendar date at or after `boundary_expr`.

    A NULL boundary means "this root never rolls": the comparison is NULL, which is not
    true, so the ELSE branch keeps the calendar date. That is what lets one expression
    serve a file carrying roots with different session shapes.

    The outer cast matters: `DATE + INTERVAL 1 DAY` is a TIMESTAMP in DuckDB, and a trade
    date that is sometimes a timestamp compares and groups differently.
    """
    return (
        f"CAST(CASE WHEN CAST({ts_expr} AS TIME) >= {boundary_expr}"
        f" THEN CAST({ts_expr} AS DATE) + INTERVAL 1 DAY"
        f" ELSE CAST({ts_expr} AS DATE) END AS DATE)"
    )


@dataclass(frozen=True)
class CalendarRow:
    """One generated `ref.session_calendar` row."""

    exchange: str
    root: str
    trade_date: date
    session_open_utc: datetime | None
    session_close_utc: datetime | None
    is_holiday: bool
    is_early_close: bool
    halt_windows_utc: list[dict[str, str]]
    expected_slots_1m: int | None


def _local_to_utc(day: date, moment: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, moment, tzinfo=tz).astimezone(ZoneInfo("UTC"))


def session_bounds(
    trade_date: date, product: Product, tz: ZoneInfo
) -> tuple[datetime, datetime]:
    """Open and close instants of the session that closes on `trade_date`.

    For a session that spans midnight the open falls on the previous calendar day — which is
    why a Monday trade date opens on Sunday evening, and why Sunday-evening bars are not
    weekend records.
    """
    session = product.session
    open_day = trade_date - timedelta(days=1) if session.spans_midnight else trade_date
    return (
        _local_to_utc(open_day, session.open_local, tz),
        _local_to_utc(trade_date, session.close_local, tz),
    )


def _halt_windows_utc(
    trade_date: date, product: Product, tz: ZoneInfo
) -> list[dict[str, str]]:
    """Expand the profile's halt list for one date. A list, because ZC has two windows."""
    session = product.session
    windows: list[dict[str, str]] = []
    for start_local, end_local in session.halt_windows:
        # A halt that starts in the evening block belongs to the previous calendar day,
        # by the same rule that puts the session open there.
        start_day = (
            trade_date - timedelta(days=1)
            if session.spans_midnight and start_local >= session.open_local
            else trade_date
        )
        end_day = (
            trade_date - timedelta(days=1)
            if session.spans_midnight and end_local > session.open_local
            else trade_date
        )
        windows.append(
            {
                "start_utc": _local_to_utc(start_day, start_local, tz).isoformat(),
                "end_utc": _local_to_utc(end_day, end_local, tz).isoformat(),
            }
        )
    return windows


def generate_calendar(
    root: str,
    start: date,
    end: date,
    *,
    product: Product | None = None,
) -> list[CalendarRow]:
    """Expand a product's session rules across a date range.

    `ref.session_calendar` is generated, never hand-maintained: keeping the session
    definition in one place is what makes it inspectable and testable. Weekend trade dates
    are skipped — a Sunday-evening bar belongs to Monday's session, so no session ever
    *closes* on a weekend.
    """
    product = product or PRODUCTS_BY_ROOT[root]
    tz = ZoneInfo(product.timezone)
    holidays = holiday_index(range(start.year, end.year + 1))

    rows: list[CalendarRow] = []
    day = start
    while day <= end:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue

        holiday = holidays.get(day)
        is_holiday = bool(holiday and holiday.is_holiday)
        is_early_close = bool(holiday and holiday.is_early_close)

        if is_holiday:
            expected: int | None = 0
            open_utc = close_utc = None
            halts: list[dict[str, str]] = []
        else:
            # An early close has a session but an unknown truncated grid; null says so.
            expected = None if is_early_close else product.session.expected_slots_1m
            open_utc, close_utc = session_bounds(day, product, tz)
            halts = _halt_windows_utc(day, product, tz)

        rows.append(
            CalendarRow(
                exchange=product.exchange,
                root=product.root,
                trade_date=day,
                session_open_utc=open_utc,
                session_close_utc=close_utc,
                is_holiday=is_holiday,
                is_early_close=is_early_close,
                halt_windows_utc=halts,
                expected_slots_1m=expected,
            )
        )
        day += timedelta(days=1)
    return rows
