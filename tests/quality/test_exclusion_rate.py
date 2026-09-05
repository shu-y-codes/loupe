"""Measure what the `error` rules actually exclude from the real corpus.

`plans/02-quality.md` done-when 12: seven `error` rules land at once, and this is the first
time anything is excluded at all. Nothing downstream should be built on
`dq.market_record_clean` before somebody has looked at what left it — a quirk tripping one
rule on a few percent of one root would surface in slice 3 as an oracle-test failure that
looks like an aggregation bug (spec §17).

The measured result is recorded in the plan. What is asserted here is the *shape* of it, so
that a future change to a severity or a threshold that quietly starts excluding real data
fails a test rather than moving a number nobody is watching.

Skipped unless the corpus has been fetched: it carries no redistribution licence and is never
committed (`specs/sample-corpus.md` §1).
"""

from __future__ import annotations

import pytest

from loupe.data import load_file
from loupe.quality import exclusion_rate, run_rules

#: Every rule whose default cleaning removes a record: the seven `error` rules the plan
#: names, `UNQ.EXACT_DUPLICATE` for `dedupe_drop`, and the three further `error` rules the
#: catalogue carries. Running exactly this set keeps the measurement about exclusion and
#: leaves the grid-expansion rules, which exclude nothing, out of it.
EXCLUDING_RULES = (
    "CMP.NULL_FIELD",
    "UNQ.EXACT_DUPLICATE",
    "UNQ.KEY_CONFLICT",
    "VAL.NON_POSITIVE_PRICE",
    "VAL.NEGATIVE_VOLUME",
    "CON.HIGH_LT_LOW",
    "CON.OPEN_OUT_OF_RANGE",
    "CON.CLOSE_OUT_OF_RANGE",
    "CON.WEEKEND_RECORD",
    "TIM.FUTURE_TIMESTAMP",
    "TIM.AFTER_EXPIRY",
)


@pytest.fixture(scope="module")
def corpus_exclusions(samples_dir):
    """Load the fetched corpus once and run every rule that can exclude a record.

    Module-scoped because loading 48 files takes the better part of a minute and doing it
    five times would make the measurement not worth having. `samples_dir` is session-scoped
    so this fixture can depend on it without importing `tests.conftest` as a package.
    """
    from loupe.data import apply_schema, connect, seed_reference
    from loupe.quality import seed_quality

    con = connect(":memory:")
    apply_schema(con)
    seed_reference(con, manifest=samples_dir / "files.csv")
    seed_quality(con)

    for path in sorted((samples_dir / "data").rglob("*.parquet")):
        load_file(con, path)

    result = run_rules(con, rule_ids=EXCLUDING_RULES)
    yield con, result, exclusion_rate(con)
    con.close()


@pytest.mark.samples
def test_the_exclusion_rate_is_a_rounding_error(corpus_exclusions):
    """2 of 711,484 records, 0.00028%. Measured, not assumed.

    It was 43 when this slice shipped. The 41 vendor daily settlement rows came back once
    `CON.CLOSE_OUT_OF_RANGE` learned that a daily close is a settlement rather than a trade
    (`plans/02-quality.md`, superseding banner).
    """
    _con, _result, report = corpus_exclusions

    assert report["records"] > 700_000
    assert report["excluded_pct"] < 0.05
    assert report["excluded"] < 100


@pytest.mark.samples
def test_only_two_rules_find_anything_at_all(corpus_exclusions):
    """Five of the seven `error` rules find nothing at all across 711,484 records.

    Zero nulls, zero key conflicts, zero non-positive prices, zero negative volumes and zero
    inverted ranges: the corpus is genuinely clean, which is why the demo needs labelled
    injection rather than the sample on its own (`specs/sample-corpus.md` §7.5).
    """
    _con, result, _report = corpus_exclusions

    assert set(result.findings_by_rule) <= {
        "CON.OPEN_OUT_OF_RANGE",
        "CON.CLOSE_OUT_OF_RANGE",
    }


@pytest.mark.samples
def test_every_exclusion_is_a_daily_row(corpus_exclusions):
    """Not one of the 681,382 minute records is excluded; both survivors are daily.

    They are `CON.OPEN_OUT_OF_RANGE` — one ES, one SR3 — and that rule has no settlement
    story to tell: an open is a trade at either granularity, so it stays `error`.
    """
    con, _result, report = corpus_exclusions

    by_frequency = dict(
        con.execute(
            """
            SELECT r.frequency, count(DISTINCT a.record_id)
            FROM stage.market_record r
            LEFT JOIN dq.cleaning_action a ON a.record_id = r.record_id
            GROUP BY 1
            """
        ).fetchall()
    )
    assert by_frequency["minute"] == 0
    assert by_frequency["daily"] > 0
    assert {row["rule_id"] for row in report["by_rule"]} == {"CON.OPEN_OUT_OF_RANGE"}


@pytest.mark.samples
def test_the_settlement_rows_are_reported_and_kept(corpus_exclusions):
    """The convention, measured on the real corpus.

    42 vendor daily rows carry a close outside their own range, and 39 of them both have zero
    volume and have `open = high = low` — an untraded deferred contract carrying its prior
    range with a settlement struck elsewhere (`specs/sample-corpus.md` §7.5). Every one is
    reported at `warning` and none is excluded, so the contract-day reaches
    `mart.bar_daily` and `CON.DERIVED_BAR_INVALID` explains it on the bar. Excluding them
    was accurate about the arithmetic and wrong about the data.
    """
    con, _result, _report = corpus_exclusions

    severities = dict(
        con.execute(
            """
            SELECT severity, count(*) FROM dq.dq_finding
            WHERE rule_id = 'CON.CLOSE_OUT_OF_RANGE' GROUP BY 1
            """
        ).fetchall()
    )
    assert set(severities) == {"warning"}
    assert severities["warning"] > 30

    untraded, flat, total = con.execute(
        """
        SELECT sum(CASE WHEN coalesce(r.volume, 0) = 0 THEN 1 ELSE 0 END),
               sum(CASE WHEN r.open = r.high AND r.high = r.low THEN 1 ELSE 0 END),
               count(*)
        FROM dq.dq_finding f
        JOIN stage.market_record r ON r.record_id = f.record_id
        WHERE f.rule_id = 'CON.CLOSE_OUT_OF_RANGE'
        """
    ).fetchone()
    assert untraded / total > 0.85
    assert flat / total > 0.85

    kept = con.execute(
        """
        SELECT count(*) FROM dq.dq_finding f
        WHERE f.rule_id = 'CON.CLOSE_OUT_OF_RANGE'
          AND NOT EXISTS (
            SELECT 1 FROM dq.cleaning_action a WHERE a.record_id = f.record_id
          )
        """
    ).fetchone()[0]
    assert kept >= total - 1  # the one ESZ25 row that also trips CON.OPEN_OUT_OF_RANGE


@pytest.mark.samples
def test_no_root_loses_a_meaningful_share_of_its_records(corpus_exclusions):
    """The failure mode this measurement exists to catch: one root quietly losing percent.

    The worst root here is ES daily at 0.029%, a single row. It was CL daily at 0.27% before
    the settlement rows stopped being excluded. A threshold change that pushed any root into
    whole percentages would break this.
    """
    _con, _result, report = corpus_exclusions

    worst = max(report["by_root"], key=lambda row: row["excluded_pct"])
    assert worst["excluded_pct"] < 1.0


@pytest.mark.samples
def test_the_clean_view_is_the_raw_table_minus_exactly_those_records(corpus_exclusions):
    con, _result, report = corpus_exclusions

    raw = con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0]
    clean = con.execute("SELECT count(*) FROM dq.market_record_clean").fetchone()[0]
    assert raw - clean == report["excluded"]
