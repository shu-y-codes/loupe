"""Reference seeding: products, ticks, contracts and the generated session calendar."""

from __future__ import annotations

from datetime import date

import pytest

from loupe.data import seed_reference
from loupe.data.profiles import PRODUCTS_BY_ROOT


def test_products_are_seeded_for_every_root_in_the_corpus(con):
    roots = {row[0] for row in con.execute("SELECT root FROM ref.product").fetchall()}
    assert roots == {"CL", "ES", "GC", "SB", "SR3", "VX", "ZC", "ZN"}


def test_exchange_has_no_default(con):
    """Six exchanges are present; a 'CME' default would be wrong for a third of the corpus."""
    exchanges = {row[0] for row in con.execute("SELECT exchange FROM ref.product").fetchall()}
    assert exchanges == {"CBOT", "CFE", "CME", "COMEX", "ICEUS", "NYMEX"}


def test_spans_midnight_is_computed_by_the_schema(con):
    rows = dict(con.execute("SELECT root, spans_midnight FROM ref.product").fetchall())
    assert rows["ES"] is True
    assert rows["ZC"] is True
    assert rows["SB"] is False


def test_measured_tick_sizes(con):
    ticks = dict(con.execute("SELECT root, tick_size FROM ref.product").fetchall())
    assert ticks["ES"] == 0.25
    assert ticks["ZN"] == 0.015625  # 1/64, exact in IEEE 754
    assert ticks["SR3"] == 0.0025
    assert ticks["GC"] == 0.10


def test_tick_is_keyed_by_root_frequency_and_field(con):
    """Same root, same nominal tick, opposite verdicts across the two configs."""
    minute_close, daily_close = con.execute(
        """
        SELECT
          (SELECT tick_size FROM ref.tick WHERE root='VX' AND frequency='minute' AND field='close'),
          (SELECT tick_size FROM ref.tick WHERE root='VX' AND frequency='daily'  AND field='close')
        """
    ).fetchone()
    assert minute_close == 0.01
    assert daily_close is None


def test_settlement_bearing_daily_close_is_exempt_not_given_a_fake_lattice(con):
    exempt = con.execute(
        "SELECT count(*) FROM ref.tick WHERE exempt AND frequency = 'daily' AND field = 'close'"
    ).fetchone()[0]
    assert exempt == len(PRODUCTS_BY_ROOT)
    # Every other field keeps its measured lattice.
    non_exempt_nulls = con.execute(
        "SELECT count(*) FROM ref.tick WHERE NOT exempt AND tick_size IS NULL"
    ).fetchone()[0]
    assert non_exempt_nulls == 0


def test_seed_is_idempotent(con):
    before = con.execute("SELECT count(*) FROM ref.tick").fetchone()[0]
    seed_reference(con)
    assert con.execute("SELECT count(*) FROM ref.tick").fetchone()[0] == before


@pytest.mark.samples
def test_contracts_are_seeded_from_the_vendor_manifest(con, samples_dir):
    summary = seed_reference(con, manifest=samples_dir / "files.csv")
    assert summary.contracts == 40
    assert summary.calendar_rows > 0

    root, month_code, contract_month, exchange, inferred = con.execute(
        "SELECT root, month_code, contract_month, exchange, dates_inferred "
        "FROM ref.contract WHERE contract_id = 'ESZ25'"
    ).fetchone()
    assert (root, month_code, exchange) == ("ES", "Z", "CME")
    assert contract_month == date(2025, 12, 1)
    # The package carries no expiry reference data, so every date here is observed.
    assert inferred is True


@pytest.mark.samples
def test_every_manifest_symbol_parses_and_agrees_with_the_reference(con, samples_dir):
    """The parse is validated against files.csv rather than trusted."""
    seed_reference(con, manifest=samples_dir / "files.csv")
    disagreements = con.execute(
        "SELECT contract_id FROM ref.contract WHERE parse_confidence < 1.0"
    ).fetchall()
    assert disagreements == []


@pytest.mark.samples
def test_seeded_holidays_are_absent_from_the_vendor_daily_dates(con, samples_dir):
    """Validate the hardcoded list against observed data rather than trusting it.

    Full closures must not appear in the daily files. Partial holidays legitimately do, which
    is exactly why only full closures set `is_holiday`.
    """
    from loupe.data import load_file

    load_file(con, samples_dir / "data/daily/CME/ES/ESZ25.parquet")
    observed = con.execute(
        "SELECT min(trade_date), max(trade_date) FROM stage.market_record"
    ).fetchone()

    clashes = con.execute(
        """
        SELECT c.trade_date
        FROM ref.session_calendar c
        JOIN stage.market_record r
          ON r.trade_date = c.trade_date AND r.contract_id = 'ESZ25'
        WHERE c.root = 'ES' AND c.is_holiday
          AND c.trade_date BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 1
        """,
        list(observed),
    ).fetchall()
    assert clashes == []


@pytest.mark.samples
def test_calendar_covers_every_observed_trade_date(con, samples_dir):
    """A session the data contains and the calendar does not is a hole in the grid."""
    from loupe.data import load_file

    load_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    uncovered = con.execute(
        """
        SELECT count(DISTINCT r.trade_date)
        FROM stage.market_record r
        LEFT JOIN ref.session_calendar c
          ON c.root = 'ES' AND c.trade_date = r.trade_date
        WHERE c.trade_date IS NULL
        """
    ).fetchone()[0]
    assert uncovered == 0


@pytest.mark.samples
def test_full_sessions_match_the_seeded_expected_grid(con, samples_dir):
    """The modal complete ES session is 1,380 one-minute slots, not 1,365.

    There is no 15:15-15:30 halt in this data. Getting this wrong makes every completeness
    percentage slightly optimistic in a way no other check would catch.
    """
    from loupe.data import load_file

    load_file(con, samples_dir / "data/minute/CME/ES/ESZ25.parquet")
    busiest = con.execute(
        """
        SELECT max(n) FROM (
          SELECT trade_date, count(*) AS n FROM stage.market_record
          WHERE frequency = 'minute' GROUP BY 1
        )
        """
    ).fetchone()[0]
    expected = con.execute(
        "SELECT DISTINCT expected_slots_1m FROM ref.session_calendar "
        "WHERE root = 'ES' AND NOT is_holiday AND expected_slots_1m IS NOT NULL"
    ).fetchall()
    assert expected == [(1380,)]
    assert busiest == 1380


@pytest.mark.samples
def test_full_closures_have_no_row_anywhere_in_the_corpus(con, samples_dir):
    """The seeded full-closure list, checked against all 40 daily files at once.

    This is the assertion that moved Good Friday, Memorial Day, Thanksgiving and the rest
    out of the full-closure list: they all carry rows, and usually volume.
    """
    from loupe.data.profiles import holiday_index

    dates = con.execute(
        f"SELECT min(date), max(date) FROM read_parquet('{samples_dir}/data/daily/*/*/*.parquet')"
    ).fetchone()
    closures = [
        holiday.day
        for holiday in holiday_index(range(dates[0].year, dates[1].year + 1)).values()
        if holiday.is_holiday
    ]
    with_rows = con.execute(
        f"""
        SELECT DISTINCT date
        FROM read_parquet('{samples_dir}/data/daily/*/*/*.parquet')
        WHERE date IN (SELECT unnest(?))
        ORDER BY 1
        """,
        [closures],
    ).fetchall()
    assert with_rows == []


@pytest.mark.samples
def test_early_closes_are_not_over_marked(con, samples_dir):
    """A day we call an early close must actually have a session.

    Marking a trading day shut is the more damaging error of the two: it removes the day
    from the expected grid entirely instead of merely leaving its denominator unknown.
    """
    from loupe.data.profiles import holidays

    checked = {
        "Good Friday": date(2023, 4, 7),
        "Memorial Day": date(2025, 5, 26),
        "Independence Day": date(2025, 7, 4),
        "Thanksgiving": date(2025, 11, 27),
        "Christmas Eve": date(2024, 12, 24),
    }
    for name, day in checked.items():
        seeded = {h.name: h for h in holidays(day.year)}
        assert seeded[name].is_early_close, name
        assert not seeded[name].is_holiday, name
        rows = con.execute(
            f"SELECT count(*) FROM read_parquet('{samples_dir}/data/daily/*/*/*.parquet') "
            "WHERE date = ?",
            [day],
        ).fetchone()[0]
        assert rows > 0, f"{name} on {day} was marked an early close but has no rows"


@pytest.mark.samples
def test_new_years_eve_is_a_trading_day_not_a_shifted_holiday(con, samples_dir):
    """2021-12-31 carries 506 lots. Federal observance shifts; the exchange does not."""
    from loupe.data.profiles import holiday_index

    index = holiday_index(range(2021, 2023))
    assert date(2021, 12, 31) not in index
    volume = con.execute(
        f"SELECT sum(volume) FROM read_parquet('{samples_dir}/data/daily/*/*/*.parquet') "
        "WHERE date = DATE '2021-12-31'"
    ).fetchone()[0]
    assert volume == 506
