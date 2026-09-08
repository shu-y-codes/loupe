"""Reviewer-strip families, card counts and OHLCV overlay marks.

`specs/dq-rules-and-scoring.md` §11.8 and `specs/api-contract.md` §6.6. Labelling only —
rule triggers are unchanged. A widget that grouped `findings[]` to draw the strip would
have missed these helpers.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from helpers import findings

from loupe.insights import build_bars
from loupe.quality import CATALOGUE, review_checks, strip_family
from loupe.quality.catalogue import STRIP_FAMILY_RULES
from loupe.quality.review import _bar_dates, _invalid_picture, _pattern_picture


def test_every_rule_is_in_exactly_one_strip_family_or_off_strip():
    """A rule is gaps, duplicates, invalid, or off-strip — never two, never none."""
    claimed = [rule_id for rules in STRIP_FAMILY_RULES.values() for rule_id in rules]
    assert len(claimed) == len(set(claimed))
    for spec in CATALOGUE:
        family = strip_family(spec.rule_id)
        assert family in {"gaps", "duplicates", "invalid", "off_strip"}
        in_sets = [name for name, rules in STRIP_FAMILY_RULES.items() if spec.rule_id in rules]
        if family == "off_strip":
            assert in_sets == []
        else:
            assert in_sets == [family]


def test_outliers_are_off_strip():
    assert strip_family("OUT.RETURN_MAD") == "off_strip"
    assert strip_family("OUT.VOLUME_MAD") == "off_strip"


def test_null_field_counts_as_invalid_not_a_gap():
    assert strip_family("CMP.NULL_FIELD") == "invalid"
    assert strip_family("CMP.MISSING_TIMESTAMP") == "gaps"


def test_a_gap_marks_an_absent_day_with_no_bar_row(qcon, run_fixture):
    """CMP.SESSION_MISSING is a dashed column, never a zero-filled bar."""
    _, result = run_fixture("cmp_session_missing.csv")
    build_bars(qcon)

    page = review_checks(qcon, "ESZ25", family="gaps")
    absent_day = date(2025, 9, 16)
    mark = next(row for row in page.overlay["ohlcv"] if row["trade_date"] == absent_day.isoformat())
    assert mark["session"] == "absent"
    assert mark["partial_gap"] is False

    bar = qcon.execute(
        "SELECT 1 FROM mart.bar_daily WHERE contract_id = 'ESZ25' AND trade_date = ?",
        [absent_day],
    ).fetchone()
    assert bar is None

    gaps = next(card for card in page.families if card["family"] == "gaps")
    assert gaps["count"] >= 1


def test_invalid_paints_a_present_bar(qcon, run_fixture):
    """The bar exists; the overlay paints it. Frequency-aware max_severity is the wrong key."""
    _, result = run_fixture("con_close_out_of_range.csv")
    build_bars(qcon)

    page = review_checks(qcon, "ESZ25", family="invalid")
    rows = findings(qcon, result.run_id, "CON.CLOSE_OUT_OF_RANGE")
    assert rows, "fixture must fire the invalid rule"
    day = rows[0]["trade_date"]
    mark = next(row for row in page.overlay["ohlcv"] if row["trade_date"] == day.isoformat())
    assert mark["invalid"] is True
    assert mark["session"] == "present"

    bar = qcon.execute(
        "SELECT 1 FROM mart.bar_daily WHERE contract_id = 'ESZ25' AND trade_date = ?",
        [day],
    ).fetchone()
    assert bar is not None


def test_minute_missing_timestamp_marks_the_derived_daily_session(qcon, run_fixture):
    """A minute gap still pins the daily candle when that is the chart on screen."""
    _, result = run_fixture("cmp_missing_timestamp.csv")
    build_bars(qcon)

    rows = findings(qcon, result.run_id, "CMP.MISSING_TIMESTAMP")
    assert rows
    day = rows[0]["trade_date"]
    page = review_checks(qcon, "ESZ25", family="gaps")
    mark = next(row for row in page.overlay["ohlcv"] if row["trade_date"] == day.isoformat())
    assert mark["partial_gap"] is True
    assert mark["session"] == "present"


def test_outliers_do_not_count_on_a_card(qcon, run_fixture):
    _, result = run_fixture("out_return_mad.csv")
    out = findings(qcon, result.run_id, "OUT.RETURN_MAD")
    assert out, "the fixture must fire OUT.RETURN_MAD so the card filter can reject it"

    page = review_checks(qcon, "ESZ25")
    assert "Outlying log return" not in {issue["what"] for issue in page.issues}

    invalid = next(card for card in page.families if card["family"] == "invalid")
    open_invalid = [
        row[0]
        for row in qcon.execute(
            "SELECT rule_id FROM dq.dq_finding WHERE run_id = ? AND status = 'open'",
            [result.run_id],
        ).fetchall()
        if strip_family(row[0]) == "invalid"
    ]
    assert invalid["count"] == len(open_invalid)


def test_bar_dates_respect_the_quality_grain_source(qcon):
    qcon.execute(
        """
        INSERT INTO mart.bar_daily (
            contract_id, trade_date, basis, source, source_frequency,
            close_convention, open, high, low, close, volume
        ) VALUES
            ('ESZ25', DATE '2025-01-02', 'clean', 'vendor', 'daily',
             'settlement', 1, 2, 0, 1, 10),
            ('ESZ25', DATE '2025-01-03', 'clean', 'derived', 'minute',
             'last_trade', 1, 2, 0, 1, 10)
        """
    )

    minute = _bar_dates(qcon, "ESZ25", None, None, "clean", "minute")
    daily = _bar_dates(qcon, "ESZ25", None, None, "clean", "daily")

    assert minute == {date(2025, 1, 3)}
    assert daily == {date(2025, 1, 2)}


def test_invalid_picture_uses_subject_map_and_source_record(qcon, fixture_path):
    from loupe.data import load_file

    load_file(qcon, fixture_path("val_zero_volume_with_range.csv"))
    record_id, trade_date = qcon.execute(
        "SELECT record_id, trade_date FROM stage.market_record ORDER BY source_row LIMIT 1"
    ).fetchone()
    picture = _invalid_picture(
        qcon,
        [
            {
                "rule_id": "VAL.ZERO_VOLUME_WITH_RANGE",
                "label": "Zero volume with a price range",
                "trade_date": trade_date,
                "frequency": "minute",
                "record_id": record_id,
                "details": {},
            }
        ],
        "ESZ25",
        "minute",
        "clean",
    )

    assert picture["field"] == "volume"
    assert picture["evidence_frequency"] == "minute"
    assert picture["evidence_source"] == "source_record"
    assert picture["bar"]["record_id"] == record_id


def test_issues_are_only_the_selected_family(qcon, run_fixture):
    run_fixture("con_close_out_of_range.csv")
    build_bars(qcon)

    page = review_checks(qcon, "ESZ25", family="invalid", frequency="minute")

    assert page.issues
    assert {row["family"] for row in page.issues} == {"invalid"}


def test_pattern_picture_focuses_one_rule_and_dimension():
    def pattern(rule_id, dimension, bucket, lift):
        return SimpleNamespace(
            rule_id=rule_id,
            dimension=dimension,
            bucket=bucket,
            share_of_findings=0.8,
            share_of_records=0.04,
            lift=lift,
            support=40,
            distinct_days=5,
            narrative=f"{rule_id} in {bucket}",
        )

    picture = _pattern_picture(
        [
            pattern("CMP.MISSING_TIMESTAMP", "day_of_week", "Monday", 20.0),
            pattern("CMP.MISSING_TIMESTAMP", "day_of_week", "Tuesday", 10.0),
            pattern("VAL.OFF_TICK_PRICE", "hour_of_day", "12:00-13:00", 5.0),
        ]
    )

    assert picture["rule_id"] == "CMP.MISSING_TIMESTAMP"
    assert picture["dimension"] == "day_of_week"
    assert picture["patterns_total"] == 3
    assert picture["buckets_shown"] == 2
    assert {row["label"] for row in picture["buckets"]} == {"Monday", "Tuesday"}
    assert all(
        {"share_of_findings", "share_of_records", "lift", "support", "distinct_days"}
        <= set(row)
        for row in picture["buckets"]
    )
