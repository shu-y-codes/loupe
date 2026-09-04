"""Reference profiles: sessions, ticks, multipliers, holidays, and the vendor file shape.

Every session and tick figure here is measured from the corpus and owned by
`specs/sample-corpus.md` (§5 sessions, §7.2 ticks). Multipliers are contract terms and are
*not* measurable from a price series, so they come from the exchange specifications and are
the one group of values here that the data cannot confirm.

Seeding these is a configuration change, not a code change: a new venue is a new row.
Roots with no profile fall back to the data-inferred session derivation in `sessions.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta

CHICAGO = "America/Chicago"


@dataclass(frozen=True)
class SessionProfile:
    """One session shape.

    `halt_windows` holds **intra-session** halts only: a session made of N contiguous blocks
    carries N-1 of them. The gap between one session's close and the next one's open is
    already expressed by `open_local` / `close_local` and is not a halt. So the CME-family
    16:00-17:00 maintenance break is *not* listed — it falls outside a 17:00-16:00 session —
    while ZC's 07:45-08:30 break is, because it splits one session in two.

    The invariant that follows, and that `tests/data/test_sessions.py` asserts: the expected
    slot count equals the session span in minutes minus the halted minutes.
    """

    name: str
    open_local: time
    close_local: time
    expected_slots_1m: int
    halt_windows: tuple[tuple[time, time], ...] = ()

    @property
    def spans_midnight(self) -> bool:
        """17:00 open with a 16:00 close is the normal case, not an error."""
        return self.open_local > self.close_local


# Three distinct shapes across eight roots (specs/sample-corpus.md §5).
# 17:00 -> 15:59 next day, one contiguous block: 23 hours, 1,380 slots. The 16:00-16:59
# dead zone is the gap to the next session, not a halt inside this one.
CME_23H = SessionProfile(
    name="cme_23h",
    open_local=time(17, 0),
    close_local=time(16, 0),
    expected_slots_1m=1380,
)
# 02:30 -> 11:59 inside one calendar day, one block: 570 slots.
ICE_SINGLE_WINDOW = SessionProfile(
    name="ice_single_window",
    open_local=time(2, 30),
    close_local=time(12, 0),
    expected_slots_1m=570,
)
# 19:00 -> 07:44 and 08:30 -> 13:19: two blocks, so one halt. 1,100 span - 45 = 1,055 slots.
CBOT_GRAIN_TWO_WINDOW = SessionProfile(
    name="cbot_grain_two_window",
    open_local=time(19, 0),
    close_local=time(13, 20),
    expected_slots_1m=1055,
    halt_windows=((time(7, 45), time(8, 30)),),
)


@dataclass(frozen=True)
class Product:
    """A root, its venue, its session and its measured tick."""

    root: str
    description: str
    exchange: str
    tick_size: float
    multiplier: float | None
    session: SessionProfile
    cycle: str = "quarterly"
    timezone: str = CHICAGO
    # Daily `close` is a settlement for this vendor, carried to more decimals than the tick.
    # It is exempt from the lattice check rather than given a fake one.
    daily_close_is_settlement: bool = True


PRODUCTS: tuple[Product, ...] = (
    Product("CL", "WTI Crude Oil", "NYMEX", 0.01, 1000.0, CME_23H, cycle="monthly"),
    Product("ES", "E-mini S&P 500", "CME", 0.25, 50.0, CME_23H),
    Product("GC", "Gold", "COMEX", 0.10, 100.0, CME_23H, cycle="G,J,M,Q,V,Z"),
    Product("SB", "Sugar No. 11", "ICEUS", 0.01, 1120.0, ICE_SINGLE_WINDOW, cycle="H,K,N,V"),
    Product("SR3", "Three-Month SOFR", "CME", 0.0025, 2500.0, CME_23H),
    # VX is seeded on the CME profile. Three bars in 373,886 sit at 16:00; letting those
    # raise a warning is more honest than a 1,381-slot profile for three rows.
    Product("VX", "Cboe Volatility Index", "CFE", 0.01, 1000.0, CME_23H, cycle="monthly"),
    Product("ZC", "Corn", "CBOT", 0.25, 50.0, CBOT_GRAIN_TWO_WINDOW, cycle="H,K,N,U,Z"),
    Product("ZN", "10-Year T-Note", "CBOT", 0.015625, 1000.0, CME_23H),
)

PRODUCTS_BY_ROOT: dict[str, Product] = {p.root: p for p in PRODUCTS}
KNOWN_ROOTS: set[str] = set(PRODUCTS_BY_ROOT)


# ---------------------------------------------------------------- vendor file shape


@dataclass(frozen=True)
class VendorProfile:
    """How one vendor's files map onto `stage.market_record`.

    Supporting a new vendor layout is a new profile, not new code. `column_mapping` is not a
    bijection: `timestamp_chicago_wall` feeds the derived pair `ts_exchange` / `ts_utc`, and
    the columns we deliberately decline are recorded as `unmapped` so the preview can show
    that they were seen and rejected.
    """

    name: str
    frequency: str
    required_columns: tuple[str, ...]
    column_mapping: dict[str, str | list[str]]
    unmapped: tuple[str, ...] = ()
    source_timezone: str = CHICAGO
    ts_convention: str = "interval_start"
    bar_interval: str = "1 minute"
    session_boundary: str = f"session_close 17:00 {CHICAGO}"
    notes: str = ""

    def mapping_document(self) -> dict[str, object]:
        doc: dict[str, object] = dict(self.column_mapping)
        for column in self.unmapped:
            doc[column] = None
        return doc


HF_SAMPLE_MINUTE = VendorProfile(
    name="hf_public_futures_sample_v1.minute",
    frequency="minute",
    required_columns=("contract_symbol", "timestamp_chicago_wall", "open", "high", "low", "close"),
    column_mapping={
        "contract_symbol": "contract_id",
        "timestamp_chicago_wall": ["ts_exchange", "ts_utc"],
        "timestamp_ms": "ts_source",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    },
    # trading_date is a Chicago calendar date and disagrees with the vendor's own daily
    # boundary; we derive the session date instead. minute_of_day is redundant.
    unmapped=("trading_date", "minute_of_day", "root_id", "root", "exchange"),
    bar_interval="1 minute",
    notes=(
        "timestamp_ms is a Chicago wall-clock reading encoded through a UTC epoch function, "
        "not an instant. The wall-clock column is the one we trust."
    ),
)

HF_SAMPLE_DAILY = VendorProfile(
    name="hf_public_futures_sample_v1.daily",
    frequency="daily",
    required_columns=("contract_symbol", "date", "open", "high", "low", "close"),
    column_mapping={
        "contract_symbol": "contract_id",
        "date": ["trade_date", "ts_exchange", "ts_utc"],
        "timestamp_ms": "ts_source",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "open_interest": "open_interest",
    },
    unmapped=("root_id", "root", "exchange"),
    bar_interval="1 day",
    # The vendor's daily `date` is already a session date on the 17:00 roll
    # (specs/sample-corpus.md §6.1), so it is taken as the trade date directly.
    session_boundary="column:date (vendor session date, 17:00 roll)",
    notes="close is a settlement struck near 15:00 CT, not a last trade.",
)


# ---------------------------------------------------------------------- holidays


@dataclass(frozen=True)
class Holiday:
    """A date on which the venue is shut, or shuts early.

    Only *full closures* set `is_holiday`, and in this corpus there are exactly two of them:
    **New Year's Day and Christmas Day**, the only dates with no daily row for any contract
    in any year from 2017 to 2026. Every other US market holiday — Good Friday, Memorial
    Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, MLK Day, Presidents Day —
    carries rows, and usually volume, because CME Globex runs a shortened session on them.

    Marking those as holidays would tell the completeness rule that no session was expected
    on a day that plainly has one. They are `is_early_close` instead, with a **null**
    expected slot count: the session exists and we do not know its truncated grid, and a
    null is the honest way to say the denominator is unknown rather than zero.

    There is also no US-observance shifting here. Federal observance moves New Year's Day
    back to Friday 31 December when 1 January falls on a Saturday; the exchange does not,
    and 2021-12-31 carries 506 lots across 11 contracts in this corpus. A closure that falls
    on a weekend simply has no trade date to mark (`specs/sample-corpus.md` §5.2).
    """

    day: date
    name: str
    is_holiday: bool
    is_early_close: bool = False


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth (1-based) `weekday` of a month; n = -1 means the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    last_day = (date(year, month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _observed(day: date) -> date:
    """Exchange observance: a Sunday closure moves to Monday. A Saturday one does not move.

    The federal calendar shifts a Saturday holiday back to the preceding Friday. The
    exchange keeps that Friday open, so shifting here would mark a normal trading day shut.
    A Saturday date is left alone and never becomes a trade date, because the calendar
    generator skips weekends.
    """
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm. Good Friday is an early close in this corpus, not a closure."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    month, day = divmod(h + lam - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holidays(year: int) -> list[Holiday]:
    """US exchange holidays for one year: two full closures, the rest early closes.

    Hardcoded rather than sourced, per `specs/sample-corpus.md` §5.2 — and validated against
    the observed daily dates by `tests/data/test_reference_seed.py` rather than trusted. That
    validation is what moved Good Friday, Memorial Day and the rest out of the full-closure
    list: the data has rows on every one of them.
    """
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    good_friday = _easter(year) - timedelta(days=2)
    christmas = _observed(date(year, 12, 25))
    independence = _observed(date(year, 7, 4))

    full = [
        Holiday(_observed(date(year, 1, 1)), "New Year's Day", True),
        Holiday(christmas, "Christmas Day", True),
    ]
    early = [
        Holiday(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day", False, True),
        Holiday(_nth_weekday(year, 2, 0, 3), "Presidents Day", False, True),
        Holiday(good_friday, "Good Friday", False, True),
        Holiday(_nth_weekday(year, 5, 0, -1), "Memorial Day", False, True),
        Holiday(independence - timedelta(days=1), "Independence Day eve", False, True),
        Holiday(independence, "Independence Day", False, True),
        Holiday(_nth_weekday(year, 9, 0, 1), "Labor Day", False, True),
        Holiday(thanksgiving, "Thanksgiving", False, True),
        Holiday(thanksgiving + timedelta(days=1), "Day after Thanksgiving", False, True),
        Holiday(christmas - timedelta(days=1), "Christmas Eve", False, True),
    ]
    # Juneteenth became a US federal holiday in 2021 and a CME closure from 2022.
    if year >= 2022:
        early.append(Holiday(_observed(date(year, 6, 19)), "Juneteenth", False, True))
    return full + early


def holiday_index(years: range) -> dict[date, Holiday]:
    """Every holiday across `years`, keyed by date. Later entries do not overwrite earlier."""
    index: dict[date, Holiday] = {}
    for year in years:
        for holiday in holidays(year):
            index.setdefault(holiday.day, holiday)
    return index
