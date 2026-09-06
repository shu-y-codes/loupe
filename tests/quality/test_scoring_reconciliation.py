"""Reconciliation in the score — §8.6's sub-score and §11.3's renormalisation.

Kept apart from `test_scoring.py` because the questions are different. That file asks whether
the five always-in-scope dimensions add up; this one asks whether the **conditional** dimension
enters honestly, and the two things §11.3 and §8.6 forbid by name are the assertions that
matter most:

- a contract with no reconcilable sessions gets **no** reconciliation score — not 100, not 0;
- `REC.CLOSE_CONVENTION` never enters the numerator.

Both are failures that look like successes. A missing dimension scored 100 rewards uploading
less; scored 0 punishes it; and an `info` rule in the numerator would quietly drag a perfectly
reconciled contract down for behaving exactly as a settlement feed behaves.
"""

from __future__ import annotations

import pytest
from helpers import set_param

from loupe.data import load_file
from loupe.quality import assess
from loupe.quality.reconciliation import CROSS

OPEN_GATE = 0.001


def _load_pair(qcon, fixture_path, stem: str, *, coverage: float | None = OPEN_GATE):
    load_file(qcon, fixture_path(f"{stem}_minute.csv"))
    load_file(qcon, fixture_path(f"{stem}_daily.csv"))
    if coverage is not None:
        set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", coverage)
    return assess(qcon, min_records=1)


def _slice(scores, contract_id, frequency):
    return next(
        s for s in scores if s.contract_id == contract_id and s.frequency == frequency
    )


# ------------------------------------------------------------------- the in-scope path


def test_reconciliation_enters_the_score_when_both_grains_exist(qcon, fixture_path):
    """§8.6 over reconcilable sessions: one defect of two sessions is 50.

    The fixture's two sessions are the whole arithmetic — one disagrees on `high`, one agrees —
    so the sub-score is checkable by hand rather than asserted to be "some number".
    """
    _, scores = _load_pair(qcon, fixture_path, "rec_ohlc_disagree")
    daily = _slice(scores, "ESZ25", "daily")

    reconciliation = daily.dimensions["reconciliation"]
    assert reconciliation.score == pytest.approx(50.0)
    assert reconciliation.denominator == 2
    assert reconciliation.basis == "reconcilable_sessions"
    assert reconciliation.affected_records == 1


def test_the_denominator_renormalises_to_1_20(qcon, fixture_path):
    """§11.3: a contract with both frequencies divides by 1.20, and says so.

    The scope signature carries `+rec` for the same reason the denominator moves — a
    six-dimension score is better evidenced than a five-dimension one and is *not the same
    measurement*, so a client must be able to tell them apart before sorting them together.
    """
    _, scores = _load_pair(qcon, fixture_path, "rec_ohlc_disagree")
    for frequency in ("daily", "minute"):
        sliced = _slice(scores, "ESZ25", frequency)
        assert sliced.weight_denominator == pytest.approx(1.20)
        assert sliced.scope_signature.endswith("+rec")
        assert sliced.dimensions_not_in_scope == []


def test_one_grain_keeps_the_1_00_denominator_and_says_why(qcon, fixture_path):
    """The other side, and the reason the disclosure is prose rather than a code.

    The reason is rendered verbatim under the score (`specs/loupe-ui-design.md`), so it has to
    be a statement about *this contract's data* — never about the build.
    """
    load_file(qcon, fixture_path("rec_ohlc_disagree_minute.csv"))
    _, scores = assess(qcon, min_records=1)
    minute = _slice(scores, "ESZ25", "minute")

    assert "reconciliation" not in minute.dimensions
    assert minute.weight_denominator == pytest.approx(1.00)
    assert not minute.scope_signature.endswith("+rec")
    (reason,) = [d for d in minute.dimensions_not_in_scope if d["dimension"] == "reconciliation"]
    assert reason["reason"] == "only one frequency uploaded for this contract"


def test_both_slices_of_one_contract_carry_the_same_sub_score(qcon, fixture_path):
    """§8.6 counts sessions the two files both hold, which is not a fact about either grain.

    So the minute slice and the daily slice share the number. Scoring the dimension per slice
    would give a contract two different reconciliation scores and no way to say which is right.
    """
    _, scores = _load_pair(qcon, fixture_path, "rec_ohlc_disagree")
    daily = _slice(scores, "ESZ25", "daily").dimensions["reconciliation"]
    minute = _slice(scores, "ESZ25", "minute").dimensions["reconciliation"]
    assert (daily.score, daily.denominator) == (minute.score, minute.denominator)


# ------------------------------------------------------- what §8.6 and §11.3 forbid by name


def test_no_reconcilable_sessions_means_no_score_rather_than_100_or_0(qcon, fixture_path):
    """§8.6, stated as a prohibition because both wrong answers are plausible ones.

    Both granularities are held for `ESZ25` and **no session is in both**: the minute tape runs
    2025-09-15 to 09-16 and the daily file 2025-10-20 to 10-22, so the reconcilable window —
    the intersection of the two — is empty. 100 would say the contract reconciles perfectly; 0
    would say it fails completely; the truth is that no session was ever put side by side.
    """
    load_file(qcon, fixture_path("rec_ohlc_disagree_minute.csv"))
    load_file(qcon, fixture_path("rec_no_overlap_daily.csv"))
    _, scores = assess(qcon, min_records=1)

    frequencies = {s.frequency for s in scores if s.contract_id == "ESZ25"}
    assert frequencies == {"minute", "daily"}, "both grains must be held, or this proves nothing"

    for frequency in ("minute", "daily"):
        sliced = _slice(scores, "ESZ25", frequency)
        assert "reconciliation" not in sliced.dimensions
        assert sliced.weight_denominator == pytest.approx(1.00)
        (reason,) = [
            d for d in sliced.dimensions_not_in_scope if d["dimension"] == "reconciliation"
        ]
        # The reason distinguishes this from a missing upload, because the fix is different:
        # nothing here is missing, the two files simply describe different months.
        assert "nothing to reconcile" in reason["reason"]
        assert "only one frequency" not in reason["reason"]


def test_close_convention_never_enters_the_numerator(qcon, fixture_path):
    """§8.4 and §11.1. The fixture's 2025-09-15 fires `REC.CLOSE_CONVENTION` and nothing else.

    Its session must still count as reconciled. An `info` rule in the numerator would score a
    contract down for the expected difference between a settlement and a last trade, which is
    exactly the punishment §8.4 exists to prevent.
    """
    result, scores = _load_pair(qcon, fixture_path, "rec_close_convention")
    assert result.findings_by_rule.get("REC.CLOSE_CONVENTION") == 1, "the info rule must fire"

    reconciliation = _slice(scores, "ESZ25", "daily").dimensions["reconciliation"]
    assert reconciliation.denominator == 2
    # 2025-09-16 is the close *disagreement* and is a defect; 2025-09-15 is the convention
    # difference and is not. One of two, not two of two.
    assert reconciliation.affected_records == 1
    assert reconciliation.score == pytest.approx(50.0)


def test_a_contract_whose_only_rec_finding_is_info_scores_100(qcon, fixture_path):
    """The sharpest form of the same rule, with the disagreement removed from the picture.

    Restricting the run to `REC.CLOSE_CONVENTION` leaves both sessions free of any defect, so
    reconciliation is a perfect 100 while an `info` finding is open on one of them. A numerator
    that counted `info` would report 50 here and look entirely reasonable.
    """
    load_file(qcon, fixture_path("rec_close_convention_minute.csv"))
    load_file(qcon, fixture_path("rec_close_convention_daily.csv"))
    result, scores = assess(qcon, min_records=1, rule_ids=("REC.CLOSE_CONVENTION",))

    assert result.findings_by_rule.get("REC.CLOSE_CONVENTION") == 1
    reconciliation = _slice(scores, "ESZ25", "daily").dimensions["reconciliation"]
    assert reconciliation.score == pytest.approx(100.0)
    assert reconciliation.affected_records == 0


# ---------------------------------------------------------------------------- the mart


def test_the_cross_grain_rollup_lands_in_the_mart(qcon, fixture_path):
    """§11.1: a `reconciliation` row at `frequency = 'cross'`, one per reconcilable session.

    `'cross'` because the row is about the **pair**; neither file holds this measurement alone.
    The per-session score is 0 or 100 because §8.6 is session-grained, and averaging the rows
    over a window reproduces the sub-score exactly.
    """
    _load_pair(qcon, fixture_path, "rec_ohlc_disagree")
    rows = qcon.execute(
        """
        SELECT trade_date, expected_records, actual_records, affected_records, dimension_score
        FROM mart.dq_metric_daily
        WHERE frequency = ? AND dimension = 'reconciliation'
        ORDER BY trade_date
        """,
        [CROSS],
    ).fetchall()

    assert [str(r[0]) for r in rows] == ["2025-09-15", "2025-09-16"]
    assert [r[3] for r in rows] == [1, 0]
    assert [r[4] for r in rows] == [0.0, 100.0]
    # The coverage the comparison rested on, which findings alone cannot recover: a session
    # that reconciled cleanly writes no finding at all.
    assert rows[0][1] == 1380 and rows[0][2] == 3


def test_no_cross_rows_exist_for_a_single_grain_contract(qcon, fixture_path):
    """Absent, not zero (§8.6). A zero row would be a measurement nobody took."""
    load_file(qcon, fixture_path("rec_ohlc_disagree_minute.csv"))
    assess(qcon, min_records=1)
    count = qcon.execute(
        "SELECT count(*) FROM mart.dq_metric_daily WHERE frequency = ?", [CROSS]
    ).fetchone()[0]
    assert count == 0
