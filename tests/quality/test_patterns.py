"""Patterns — concentration corrected for exposure (spec §12).

The fixture is built so the arithmetic is checkable by hand: `insights_pattern_hourly.csv`
spreads 96 records evenly over four hours of three sessions and puts every off-tick close in
the 12:00 hour. So the bucket holds a quarter of the records and all of the findings, and the
lift is exactly 4.0 — a number a reader can verify rather than a threshold that happened to
trip.

Both sides of both thresholds are asserted. A filter tested only from the side that admits
cannot be told apart from one that admits everything.
"""

from __future__ import annotations

import pytest

from loupe.data import load_file
from loupe.quality import assess
from loupe.quality.patterns import DIMENSIONS, find_patterns, pattern_id


@pytest.fixture
def hourly(qcon, fixture_path):
    """96 records over four hours; the off-tick closes all sit in the last of them."""
    load_file(qcon, fixture_path("insights_pattern_hourly.csv"))
    assess(qcon, min_records=1)
    return qcon


def _off_tick(patterns):
    return [p for p in patterns if p.rule_id == "VAL.OFF_TICK_PRICE"]


def test_a_concentration_is_reported_with_its_exposure(hourly):
    """The whole point of §12: a ratio, and both terms of it on the finding."""
    (found,) = _off_tick(find_patterns(hourly))

    assert found.dimension == "hour_of_day"
    assert found.bucket.startswith("12:00-13:00")
    assert found.share_of_findings == pytest.approx(1.0)
    assert found.share_of_records == pytest.approx(0.25)
    assert found.lift == pytest.approx(4.0)
    assert found.support == 24
    assert found.distinct_days == 3


def test_the_narrative_is_a_template_and_names_the_evidence(hourly):
    """§12: generated from a template, never by a language model, aggregates only."""
    (found,) = _off_tick(find_patterns(hourly))
    assert "100%" in found.narrative
    assert "12:00-13:00" in found.narrative
    assert "3 sessions" in found.narrative
    # No price, timestamp or contract-level record leaves the process in the narrative.
    assert "6606" not in found.narrative


def test_min_lift_admits_and_rejects(hourly):
    """Both sides. The measured lift is 4.0, so 3.0 admits it and 5.0 must not."""
    assert _off_tick(find_patterns(hourly, lift=3.0))
    assert not _off_tick(find_patterns(hourly, lift=5.0))


def test_min_support_admits_and_rejects(hourly):
    """Both sides. Support is 24, so 20 admits it and 25 must not."""
    assert _off_tick(find_patterns(hourly, min_support=20))
    assert not _off_tick(find_patterns(hourly, min_support=25))


def test_min_periods_requires_recurrence(hourly):
    """A concentration on three sessions is not a concentration on four."""
    assert _off_tick(find_patterns(hourly, min_periods=3))
    assert not _off_tick(find_patterns(hourly, min_periods=4))


def test_pattern_ids_are_stable_across_calls(hourly):
    """A suggestion's `from_pattern` has to name something the next request produces again."""
    first = {p.pattern_id for p in find_patterns(hourly)}
    second = {p.pattern_id for p in find_patterns(hourly)}
    assert first == second
    (found,) = _off_tick(find_patterns(hourly))
    assert found.pattern_id == pattern_id(found.rule_id, found.dimension, found.bucket)


def test_every_dimension_partitions_the_records(hourly):
    """§12's `field` and `rule` are absent because lift needs a denominator that exists.

    Asserted as a property of the dimension list rather than as a comment: every dimension
    offered must be one whose buckets divide the record set, or its `share_of_records` is
    invented. Adding one that does not would fail here rather than ship a ratio over nothing.
    """
    assert "field" not in DIMENSIONS
    assert "rule" not in DIMENSIONS
    assert set(DIMENSIONS) == {
        "hour_of_day",
        "day_of_week",
        "trade_date",
        "contract",
        "frequency",
        "batch",
    }


def test_an_unknown_dimension_is_refused_rather_than_ignored(hourly):
    with pytest.raises(ValueError, match="unknown pattern dimension"):
        find_patterns(hourly, dimensions=("field",))


def test_an_empty_corpus_yields_no_patterns(qcon):
    """No findings is not a pattern of zero; it is nothing to report."""
    assert find_patterns(qcon) == []


def test_a_scope_filter_narrows_the_report(hourly, fixture_path):
    """Scoping to a contract that holds none of the findings must empty the list.

    The other side is every other test in this file, all of which run unscoped and find the
    pattern — so this asserts the filter rather than the absence of data.
    """
    assert _off_tick(find_patterns(hourly))
    assert find_patterns(hourly, contracts=["CLZ25"]) == []


def test_frequency_scope_filters_findings_and_exposure_together(hourly):
    """A minute pattern cannot leak into a Daily quality-grain request."""
    minute = _off_tick(find_patterns(hourly, frequency="minute"))
    daily = _off_tick(find_patterns(hourly, frequency="daily"))

    assert minute
    assert daily == []
