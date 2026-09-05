"""The DQ score: per-dimension sub-scores, the renormalised mean, and the triage worklist.

The property checks the plan asks for live here: a record is counted at most once per
dimension, overall is the renormalised weighted mean over the dimensions in scope, and triage
weight cannot move any score.
"""

from __future__ import annotations

import pytest

from loupe.quality import RunScope, assess, scoped, score_if_resolved, score_slice, worklist
from loupe.quality.catalogue import SCORE_WEIGHTS


def assessed(qcon, fixture_path, name: str, **kwargs):
    from loupe.data import load_file

    batch = load_file(qcon, fixture_path(name))
    return assess(qcon, batch_id=batch.batch_id, **kwargs)


def only(scores, contract_id: str, frequency: str):
    return next(s for s in scores if (s.contract_id, s.frequency) == (contract_id, frequency))


# --------------------------------------------------------------------- shape and scope


def test_the_score_object_carries_its_scope(qcon, fixture_path):
    """§11.3: every score states which dimensions were in scope and what it divided by."""
    _, scores = assessed(qcon, fixture_path, "tim_timezone_misaligned.csv")
    score = only(scores, "ESZ25", "minute")

    assert score.dimensions_in_scope == [
        "completeness",
        "uniqueness",
        "validity",
        "consistency",
        "timeliness",
    ]
    assert score.scope_signature == "cmp+unq+val+con+tim"
    assert score.weight_denominator == pytest.approx(1.00)
    assert score.dimensions["completeness"].basis == "expected_records"
    assert score.dimensions["validity"].basis == "actual_records"


def test_reconciliation_is_out_of_scope_with_a_stated_reason(qcon, fixture_path):
    """A contract with no reconcilable sessions has no reconciliation score — not 100, not 0."""
    _, scores = assessed(qcon, fixture_path, "tim_timezone_misaligned.csv")
    score = only(scores, "ESZ25", "minute")

    assert "reconciliation" not in score.dimensions
    assert score.dimensions_not_in_scope == [
        {
            "dimension": "reconciliation",
            "reason": "only one frequency uploaded for this contract",
        }
    ]


def test_overall_is_the_renormalised_weighted_mean_over_the_dimensions_in_scope(
    qcon, fixture_path
):
    _, scores = assessed(qcon, fixture_path, "tim_timezone_misaligned.csv")
    score = only(scores, "ESZ25", "minute")

    weighted = sum(d.weight * d.score for d in score.dimensions.values())
    denominator = sum(d.weight for d in score.dimensions.values())
    assert score.overall == pytest.approx(weighted / denominator, abs=1e-4)
    # Renormalised, not defaulted: the five in-scope weights sum to 1.00, and the 0.20
    # reconciliation weight is absent from the denominator rather than scoring 0 or 100.
    assert denominator == pytest.approx(sum(SCORE_WEIGHTS.values()) - 0.20)


def test_weights_come_from_the_table_and_not_from_literals(qcon, fixture_path):
    """§11.2: `dq.score_weight` is the only weights table in the score."""
    qcon.execute("UPDATE dq.score_weight SET weight = 0.9 WHERE dimension = 'validity'")
    _, scores = assessed(qcon, fixture_path, "tim_timezone_misaligned.csv")
    score = only(scores, "ESZ25", "minute")

    assert score.dimensions["validity"].weight == pytest.approx(0.9)
    assert score.weight_denominator == pytest.approx(1.65)


def test_below_min_records_reports_insufficient_data_rather_than_a_score(qcon, fixture_path):
    """§11.5: four rows do not make a quality index."""
    _, scores = assessed(qcon, fixture_path, "cmp_partial_session.csv")
    score = only(scores, "ESZ25", "minute")

    assert score.records == 4
    assert score.insufficient_data is True
    assert score.overall is None
    # The per-dimension evidence is still there; only the composite is withheld.
    assert score.dimensions["completeness"].denominator == 1380


def test_a_slice_above_the_minimum_gets_a_score(qcon, fixture_path):
    _, scores = assessed(qcon, fixture_path, "tim_timezone_misaligned.csv")
    score = only(scores, "ESZ25", "minute")

    assert score.records == 115
    assert score.insufficient_data is False
    assert 0.0 <= score.overall <= 100.0


def test_the_minimum_is_a_parameter(qcon, fixture_path):
    _, scores = assessed(qcon, fixture_path, "cmp_partial_session.csv", min_records=1)
    assert only(scores, "ESZ25", "minute").overall is not None


# ---------------------------------------------------------------------- the arithmetic


def test_completeness_divides_by_expected_records(qcon, fixture_path):
    """Completeness is the only dimension that can detect something not in the table."""
    _, scores = assessed(qcon, fixture_path, "cmp_partial_session.csv", min_records=1)
    score = only(scores, "ESZ25", "minute")
    completeness = score.dimensions["completeness"]

    assert completeness.denominator == 1380
    assert completeness.score == pytest.approx(100.0 * 4 / 1380, abs=1e-4)


def test_a_null_field_lowers_completeness_as_well_as_being_reported(qcon, fixture_path):
    """A record that is present but incomplete is not a complete record.

    §11.1 counts every dimension's defective records, and `CMP.NULL_FIELD` is the
    completeness dimension's record-scope rule; missing slots lower the same score by being
    absent from the numerator instead.
    """
    _, scores = assessed(qcon, fixture_path, "null_fields.csv", min_records=1)
    completeness = only(scores, "ESZ25", "minute").dimensions["completeness"]

    assert completeness.affected_records == 2
    assert completeness.score == pytest.approx(100.0 * (4 - 2) / 1380, abs=1e-4)


def test_a_record_is_counted_at_most_once_per_dimension(qcon, fixture_path):
    """The planted zero price trips two validity rules; it is still one invalid record.

    Counting it twice would let a dimension score fall below what its denominator justifies.
    """
    _, scores = assessed(qcon, fixture_path, "val_non_positive_price.csv", min_records=1)
    validity = only(scores, "ESZ25", "minute").dimensions["validity"]

    assert validity.finding_count == 2
    assert validity.affected_records == 1
    assert validity.score == pytest.approx(100.0 * (1 - 1 / 3), abs=1e-4)


def test_an_info_finding_is_not_a_defect(qcon, fixture_path):
    """Only `warning`, `error` and `critical` count; `info` never enters a numerator."""
    _, scores = assessed(qcon, fixture_path, "val_extreme_volume.csv", min_records=1)
    validity = only(scores, "ESZ25", "minute").dimensions["validity"]

    assert validity.finding_count == 1
    assert validity.affected_records == 0
    assert validity.score == 100.0


def test_a_dimension_with_no_denominator_is_out_of_scope_not_perfect(qcon, fixture_path):
    """§11.1: if `expected_records` is 0, completeness is undefined rather than 100."""
    from loupe.data import load_file

    batch = load_file(qcon, fixture_path("cmp_partial_session.csv"))
    qcon.execute("UPDATE ref.session_calendar SET is_holiday = TRUE WHERE root = 'ES'")
    _, scores = assess(qcon, batch_id=batch.batch_id, min_records=1)
    score = only(scores, "ESZ25", "minute")

    assert "completeness" not in score.dimensions
    assert {d["dimension"] for d in score.dimensions_not_in_scope} == {
        "completeness",
        "reconciliation",
    }
    assert score.scope_signature == "unq+val+con+tim"


# ------------------------------------------------------------------ triage and dry runs


def test_triage_weight_cannot_move_any_score(qcon, fixture_path):
    """§11.4: `triage_weight` orders the worklist and is never a score input."""
    _, before = assessed(qcon, fixture_path, "val_non_positive_price.csv", min_records=1)

    qcon.execute("UPDATE dq.dq_rule SET triage_weight = 1000.0")
    with scoped(qcon, RunScope()) as (_inputs, _rows, _n):
        run_id = qcon.execute(
            "SELECT run_id FROM dq.dq_run ORDER BY started_at DESC LIMIT 1"
        ).fetchone()[0]
        after = score_slice(qcon, str(run_id), "ESZ25", "minute", min_records=1)

    assert after.as_json() == only(before, "ESZ25", "minute").as_json()


def test_score_if_resolved_zeroes_one_rule_and_leaves_the_others(qcon, fixture_path):
    """The same dry-run mechanism as a suggestion's `expected_effect` (§13)."""
    result, scores = assessed(qcon, fixture_path, "val_non_positive_price.csv", min_records=1)
    current = only(scores, "ESZ25", "minute")

    with scoped(qcon, RunScope()) as (_inputs, _rows, _n):
        resolved = score_if_resolved(
            qcon, result.run_id, "ESZ25", "minute", "VAL.NON_POSITIVE_PRICE", min_records=1
        )

    # The record is still invalid under VAL.PRICE_MAGNITUDE, so validity does not go to 100.
    assert current.dimensions["validity"].score < 100.0
    assert resolved.dimensions["validity"].score == current.dimensions["validity"].score


def test_resolving_a_missing_slot_rule_returns_the_slots_to_the_numerator(qcon, fixture_path):
    """A gap finding has no record id, so zeroing its defect count adds slots back."""
    result, scores = assessed(qcon, fixture_path, "cmp_missing_timestamp.csv", min_records=1)
    current = only(scores, "ESZ25", "minute")

    with scoped(qcon, RunScope()) as (_inputs, _rows, _n):
        resolved = score_if_resolved(
            qcon, result.run_id, "ESZ25", "minute", "CMP.MISSING_TIMESTAMP", min_records=1
        )

    assert resolved.dimensions["completeness"].score == 100.0
    assert current.dimensions["completeness"].score < 1.0


def test_the_worklist_ranks_by_weight_times_affected_records(qcon, fixture_path):
    result, _ = assessed(qcon, fixture_path, "val_non_positive_price.csv", min_records=1)

    with scoped(qcon, RunScope()) as (_inputs, _rows, _n):
        entries = worklist(qcon, result.run_id, "ESZ25", "minute", min_records=1)

    assert entries == sorted(entries, key=lambda e: (-e.rank, e.rule_id))
    for entry in entries:
        assert entry.rank == pytest.approx(entry.triage_weight * entry.affected_records)
        assert set(entry.score_if_resolved) == {entry.dimension, "overall", "from"}

    # An `error` seeds at 4.0 and a `warning` at 2.0 (§11.4) — but the planted error affects
    # one record while the missing grid slots affect thousands, so the warning outranks it.
    # That is the rule working: rank is meant to show whether a row is high because the
    # defect is bad or because it is everywhere.
    planted = next(e for e in entries if e.rule_id == "VAL.NON_POSITIVE_PRICE")
    assert (planted.triage_weight, planted.affected_records, planted.rank) == (4.0, 1, 4.0)
    assert entries[0].severity == "warning"
    assert entries[0].rank > planted.rank


def test_the_worklist_reorders_when_triage_weight_is_tuned(qcon, fixture_path):
    """A desk that cannot act on off-tick prices sets it low and stops seeing it at the top.

    The score does not move, because nothing about the data changed — that is the whole point
    of keeping the two numbers apart.
    """
    result, scores = assessed(qcon, fixture_path, "val_off_tick_price.csv", min_records=1)
    qcon.execute(
        "UPDATE dq.dq_rule SET triage_weight = 0.01 WHERE rule_id = 'VAL.OFF_TICK_PRICE'"
    )

    with scoped(qcon, RunScope()) as (_inputs, _rows, _n):
        entries = worklist(qcon, result.run_id, "ESZ25", "minute", min_records=1)
        rescored = score_slice(qcon, result.run_id, "ESZ25", "minute", min_records=1)

    off_tick = next(e for e in entries if e.rule_id == "VAL.OFF_TICK_PRICE")
    assert off_tick.rank == pytest.approx(0.01)
    assert entries[-1].rule_id == "VAL.OFF_TICK_PRICE"
    assert rescored.as_json() == only(scores, "ESZ25", "minute").as_json()


# ------------------------------------------------------------------------------ the mart


def test_per_dimension_rows_are_persisted_per_day(qcon, fixture_path):
    _, _scores = assessed(qcon, fixture_path, "cmp_session_missing.csv")
    rows = qcon.execute(
        """
        SELECT trade_date, dimension, expected_records, actual_records, affected_records,
               dimension_score
        FROM mart.dq_metric_daily
        WHERE contract_id = 'ESZ25' AND frequency = 'minute' AND dimension = 'completeness'
        ORDER BY trade_date
        """
    ).fetchall()

    dates = [str(row[0]) for row in rows]
    assert dates == ["2025-09-15", "2025-09-16", "2025-09-17"]
    # The absent session is a row with a denominator and no numerator, not a missing row.
    missing = rows[1]
    assert (missing[2], missing[3], missing[5]) == (1380, 0, 0.0)


def test_a_second_run_replaces_the_metric_rows_rather_than_doubling_them(qcon, fixture_path):
    from loupe.data import load_file

    batch = load_file(qcon, fixture_path("cmp_session_missing.csv"))
    assess(qcon, batch_id=batch.batch_id)
    first = qcon.execute("SELECT count(*) FROM mart.dq_metric_daily").fetchone()[0]
    assess(qcon, batch_id=batch.batch_id)

    assert qcon.execute("SELECT count(*) FROM mart.dq_metric_daily").fetchone()[0] == first
