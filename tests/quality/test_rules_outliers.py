"""`OUT.*` — the modified z-score, and why it is a question rather than a verdict."""

from __future__ import annotations

import pytest
from helpers import findings, set_param, source_rows


def test_a_return_far_outside_the_lattice_is_flagged(qcon, run_fixture):
    """Forty tick-sized returns set the scale; the planted jump is a hundred times larger."""
    _, result = run_fixture("out_return_mad.csv")
    rows = findings(qcon, result.run_id, "OUT.RETURN_MAD")

    assert len(rows) == 1
    assert source_rows(qcon, [rows[0]["record_id"]]) == [41]
    assert abs(rows[0]["details"]["modified_z"]) > 3.5


def test_outliers_are_always_info_and_never_exclude(qcon, run_fixture):
    """An outlier is a question. Any volatile window in 2021-2026 is full of legitimate ones.

    `info` is below the excluding severities, so no special case is needed in the cleaning
    policy — but the consequence is worth asserting rather than inferring.
    """
    _, result = run_fixture("out_return_mad.csv")
    rows = findings(qcon, result.run_id, "OUT.RETURN_MAD")

    assert [row["severity"] for row in rows] == ["info"]
    excluded = qcon.execute(
        "SELECT count(*) FROM dq.cleaning_action WHERE rule_id = 'OUT.RETURN_MAD'"
    ).fetchone()[0]
    assert excluded == 0


def test_the_threshold_comes_from_the_seeded_row(qcon, run_fixture):
    set_param(qcon, "OUT.RETURN_MAD", "threshold", 1000.0)
    _, result = run_fixture("out_return_mad.csv")
    assert findings(qcon, result.run_id, "OUT.RETURN_MAD") == []


def test_the_iglewicz_hoaglin_constant_comes_from_the_row_too(qcon, run_fixture):
    """`0.6745` scales the score; moving it must move the verdict, or it is a literal."""
    set_param(qcon, "OUT.RETURN_MAD", "constant", 0.0)
    _, result = run_fixture("out_return_mad.csv")
    assert findings(qcon, result.run_id, "OUT.RETURN_MAD") == []


def test_a_short_series_is_not_scored(qcon, run_fixture):
    """Below `min_records` the median and the MAD describe the noise, not the series."""
    set_param(qcon, "OUT.RETURN_MAD", "min_records", 10_000)
    _, result = run_fixture("out_return_mad.csv")
    assert findings(qcon, result.run_id, "OUT.RETURN_MAD") == []


def test_volume_mad_scores_the_volume_column(qcon, run_fixture):
    _, result = run_fixture("out_volume_mad.csv")
    rows = findings(qcon, result.run_id, "OUT.VOLUME_MAD")

    assert len(rows) == 1
    assert source_rows(qcon, [rows[0]["record_id"]]) == [41]
    assert rows[0]["details"]["log_volume"] == pytest.approx(12.43, abs=0.01)


def test_a_price_outlier_does_not_fire_the_volume_rule(qcon, run_fixture):
    """The two rules read different columns, and a fat-finger price is not a volume event."""
    _, result = run_fixture("out_return_mad.csv")
    assert findings(qcon, result.run_id, "OUT.VOLUME_MAD") == []
