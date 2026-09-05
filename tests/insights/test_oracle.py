"""The oracle: minute-derived daily bars against the vendor's own daily files.

**A consistency check between two of the same vendor's products, not an independent source of
truth.** The claim is "agrees with the vendor's daily bars", never "verified correct". It tests
a definition arrived at independently and is never used to derive one — every number the
aggregation produces comes from `specs/analytics-semantics.md` §3, which was written before
this comparison was run.

Claims and thresholds are owned by `specs/sample-corpus.md` §6; this module asserts them, and
carries none of its own. Skipped unless the corpus has been fetched: it has no redistribution
licence and is never committed (§1).

**Runs on the `clean` basis**, with the `raw` basis available for isolation. If agreement ever
drops, read slice 2's recorded exclusion rate ([02-quality.md](../../plans/02-quality.md)
done-when 12) *before* hunting an aggregation bug: records the `error` rules removed are
missing from the derived side of this comparison and present on the vendor's, so a systematic
exclusion on one root shows up here as a disagreement that looks like bad aggregation.
"""

from __future__ import annotations

import pytest

from loupe.data import load_file
from loupe.insights import build_bars

#: §6.2. Coverage is the confounder: an incomplete minute session cannot reproduce the daily
#: high and low, and comparing it to one is a statement about the gap, not about the maths.
COMPLETE_SESSION_PCT = 98.0

#: §6.5. Measured 96.48% on all three fields across eight roots; the gate is deliberately
#: looser than the measurement so that ordinary feed noise does not fail the suite.
MIN_AGREEMENT = 0.95

#: §6.1. Open agreement under the vendor's own calendar-date column, which is what the
#: recovered 17:00 roll has to beat by a wide margin for the boundary claim to hold.
CALENDAR_DATE_CEILING = 0.60


@pytest.fixture(scope="module")
def oracle(samples_dir):
    """Load the corpus once, materialise bars on both bases, hand back the connection.

    Module-scoped because loading 48 files is slow enough that doing it per test would
    make the comparison not worth having. `samples_dir` is session-scoped so this fixture
    can depend on it without importing `tests.conftest` as a package.
    """
    from loupe.data import apply_schema, connect, seed_reference  # noqa: PLC0415
    from loupe.quality import run_rules, seed_quality  # noqa: PLC0415

    con = connect(":memory:")
    apply_schema(con)
    seed_reference(con, manifest=samples_dir / "files.csv")
    seed_quality(con)
    for path in sorted((samples_dir / "data").rglob("*.parquet")):
        load_file(con, path)
    run_rules(con)
    build_bars(con)
    yield con
    con.close()


def _matched(con, basis: str = "clean"):
    """Complete sessions where a derived bar and a vendor bar exist for the same session."""
    return f"""
      SELECT d.contract_id, c.root, d.trade_date,
             d.open AS d_open, d.high AS d_high, d.low AS d_low,
             d.close AS d_close, d.volume AS d_volume,
             v.open AS v_open, v.high AS v_high, v.low AS v_low,
             v.close AS v_close, v.volume AS v_volume,
             d.completeness_pct
      FROM mart.bar_daily d
      JOIN mart.bar_daily v
        ON  v.contract_id = d.contract_id AND v.trade_date = d.trade_date
        AND v.basis = d.basis AND v.source = 'vendor'
      LEFT JOIN ref.contract c ON c.contract_id = d.contract_id
      WHERE d.basis = '{basis}' AND d.source = 'derived'
    """


def test_open_high_and_low_agree_with_the_vendor_per_root(oracle):
    """§6.2: 96.48% on all three fields across eight roots, on complete sessions."""
    rows = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)})
        SELECT root, count(*) AS sessions,
               avg(CASE WHEN d_open = v_open AND d_high = v_high AND d_low = v_low
                        THEN 1.0 ELSE 0.0 END) AS agreement
        FROM m WHERE completeness_pct >= {COMPLETE_SESSION_PCT}
        GROUP BY 1 HAVING count(*) >= 20 ORDER BY 1
        """
    ).fetchall()

    assert rows, "no complete sessions matched a vendor daily row"
    for root, sessions, agreement in rows:
        assert agreement >= MIN_AGREEMENT, f"{root}: {agreement:.4f} over {sessions} sessions"


def test_the_vendor_range_is_never_narrower_on_a_complete_session(oracle):
    """§6.2. A stronger invariant than the percentage, and it holds on every root.

    The daily file carries block and privately negotiated trades that never appear as
    continuous-market minute bars, so the vendor's range can only be the wider one. A derived
    high *above* the vendor's would mean the aggregation invented a price.
    """
    narrower = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)})
        SELECT count(*) FROM m
        WHERE completeness_pct >= {COMPLETE_SESSION_PCT}
          AND (v_high < d_high OR v_low > d_low)
        """
    ).fetchone()[0]

    assert narrower == 0


def test_the_coverage_gate_is_load_bearing_for_that_invariant(oracle):
    """§6.5: ungated it breaks, always on sparse sessions and always by a tick or less.

    Asserted rather than assumed, because a future change that quietly dropped the gate would
    otherwise leave a green suite and a false claim.
    """
    ungated = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)})
        SELECT count(*) FROM m WHERE v_high < d_high OR v_low > d_low
        """
    ).fetchone()[0]
    gated = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)})
        SELECT count(*) FROM m
        WHERE completeness_pct >= {COMPLETE_SESSION_PCT} AND (v_high < d_high OR v_low > d_low)
        """
    ).fetchone()[0]

    assert gated == 0
    assert ungated > gated, "the gate is doing nothing; the claim may have been overstated"


def test_the_session_boundary_is_recoverable_from_the_data(oracle):
    """§6.1: open agreement collapses under a calendar-date grouping.

    Kept as a live test. If this gap ever narrows, the session boundary has broken — and
    because both groupings produce 1,380 slots for a CME session, no count-based check would
    notice (§2.2.1).
    """
    session_open = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)})
        SELECT avg(CASE WHEN d_open = v_open THEN 1.0 ELSE 0.0 END)
        FROM m WHERE completeness_pct >= {COMPLETE_SESSION_PCT} AND root = 'ES'
        """
    ).fetchone()[0]

    calendar_open = oracle.execute(
        """
        WITH cal AS (
          SELECT r.contract_id, CAST(r.ts_exchange AS DATE) AS cal_date,
                 arg_min({'v': r.open}, {'t': r.ts_utc, 'r': r.source_row}).v AS open
          FROM dq.market_record_clean r
          WHERE r.frequency = 'minute'
          GROUP BY 1, 2
        )
        SELECT avg(CASE WHEN cal.open = v.open THEN 1.0 ELSE 0.0 END)
        FROM cal
        JOIN mart.bar_daily v
          ON v.contract_id = cal.contract_id AND v.trade_date = cal.cal_date
          AND v.source = 'vendor' AND v.basis = 'clean'
        JOIN ref.contract c ON c.contract_id = cal.contract_id
        WHERE c.root = 'ES'
        """
    ).fetchone()[0]

    assert session_open >= MIN_AGREEMENT
    assert calendar_open < CALENDAR_DATE_CEILING
    assert session_open > calendar_open * 1.5


def test_close_is_a_settlement_and_is_not_asserted_on(oracle):
    """§6.3. Assert the *explanation*, never the value.

    The vendor's close sits nearer the 15:00 CT mark than the session's last trade. That is
    the signature of a settlement price, and it is the reason `close_convention` exists rather
    than the reason to tune the aggregation.
    """
    row = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)}),
        complete AS (
          SELECT * FROM m WHERE completeness_pct >= {COMPLETE_SESSION_PCT} AND root = 'ES'
        ),
        at_1500 AS (
          SELECT r.contract_id, r.trade_date,
                 arg_max({{'v': r.close}}, {{'t': r.ts_utc, 'r': r.source_row}}).v AS close_1500
          FROM dq.market_record_clean r
          WHERE r.frequency = 'minute' AND CAST(r.ts_exchange AS TIME) <= TIME '14:59:00'
          GROUP BY 1, 2
        )
        SELECT median(abs(c.v_close - a.close_1500)) AS err_1500,
               median(abs(c.v_close - c.d_close))    AS err_session_end,
               count(*)
        FROM complete c JOIN at_1500 a
          ON a.contract_id = c.contract_id AND a.trade_date = c.trade_date
        """
    ).fetchone()

    err_1500, err_session_end, sessions = row
    assert sessions > 0
    assert err_1500 < err_session_end, (
        "the vendor close is no closer to 15:00 than to the session end; the settlement "
        "explanation in specs/sample-corpus.md §6.3 no longer holds"
    )


def test_vendor_volume_is_the_wider_figure(oracle):
    """§6.4. The tape carries about 95% of reported daily volume, never more than all of it."""
    row = oracle.execute(
        f"""
        WITH m AS ({_matched(oracle)})
        SELECT avg(CASE WHEN v_volume >= d_volume THEN 1.0 ELSE 0.0 END),
               median(d_volume * 1.0 / nullif(v_volume, 0))
        FROM m WHERE completeness_pct >= {COMPLETE_SESSION_PCT} AND root = 'ES'
          AND v_volume IS NOT NULL AND d_volume IS NOT NULL
        """
    ).fetchone()

    vendor_at_least_as_large, median_ratio = row
    assert vendor_at_least_as_large >= 0.9
    assert median_ratio < 1.0


def test_the_two_bases_are_named_and_comparable(oracle):
    """Running on `raw` as well is what separates an exclusion from an aggregation bug."""
    clean = oracle.execute(
        f"WITH m AS ({_matched(oracle, 'clean')}) SELECT count(*) FROM m"
    ).fetchone()[0]
    raw = oracle.execute(
        f"WITH m AS ({_matched(oracle, 'raw')}) SELECT count(*) FROM m"
    ).fetchone()[0]

    assert clean > 0 and raw > 0
    # Slice 2 measured that every excluded record is a vendor daily row, so the derived side
    # is identical and only the vendor side can lose sessions.
    assert raw >= clean
