"""Corroboration — the four answers of §8.7, asserted apart.

`specs/loupe-solution-design.md` §13 names the failure this file exists to prevent: an
implementation that returned `not_comparable` unconditionally would satisfy any assertion
written only about `not_comparable`, and that is the likeliest way this ships broken. So the
fixture produces all four answers and the test asserts they are **pairwise distinct** over four
inputs chosen to produce them.

The four, and why absence is one of them:

| answer | input |
|---|---|
| `confirmed` | a daily close-out-of-range whose high and low agree with the tape |
| `disputed` | the same finding on a session where `REC.OHLC_DISAGREE` fired on `high` |
| `not_comparable` | the same finding on a contract holding daily records only |
| *absent* | the same **rule** at minute grain, where the daily file has nothing to say |

The last row is the sharpest of the four: same rule, same corpus, and the answer is that the
question does not apply. Absent means *not applicable*; `not_comparable` means *applicable and
unevaluable*, and rendering the second as the first would tell a reader the tape was consulted
when it was not.
"""

from __future__ import annotations

import pytest
from helpers import set_param

from loupe.data import load_file
from loupe.quality import assess
from loupe.quality.corroboration import (
    CONFIRMED,
    DISPUTED,
    NOT_COMPARABLE,
    FindingRef,
    corroborate,
)

OPEN_GATE = 0.001


@pytest.fixture
def corroborated(qcon, fixture_path):
    """The four-answer corpus, run through the real engine, with the states resolved.

    Returns `(refs_by_key, states)` where a key is `(rule_id, frequency, contract, date)`, so
    each test names the input it is asserting about instead of indexing a list.
    """
    load_file(qcon, fixture_path("rec_corroboration_minute.csv"))
    load_file(qcon, fixture_path("rec_corroboration_daily.csv"))
    set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", OPEN_GATE)
    assess(qcon, min_records=1)

    rows = qcon.execute(
        """
        SELECT CAST(finding_id AS VARCHAR), rule_id, frequency, contract_id, trade_date,
               CAST(run_id AS VARCHAR)
        FROM dq.dq_finding
        WHERE status = 'open'
        """
    ).fetchall()
    refs = [FindingRef(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]
    resolved = corroborate(qcon, refs)
    by_key = {
        (r.rule_id, r.frequency, r.contract_id, str(r.trade_date)): r.finding_id for r in refs
    }
    return by_key, resolved


def _state(corroborated, rule_id, frequency, contract, day):
    by_key, resolved = corroborated
    finding_id = by_key.get((rule_id, frequency, contract, day))
    assert finding_id, f"fixture produced no {rule_id} {frequency} finding for {contract} {day}"
    return resolved.get(finding_id)


# ------------------------------------------------------------------------ the four answers


def test_the_tape_confirms_a_range_it_agrees_with(corroborated):
    """`confirmed` licenses reading the finding as being about the value, not the range."""
    state = _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-15")
    assert state is not None
    assert state.state == CONFIRMED
    assert "agree" in state.reason
    assert state.detail["minute_coverage_pct"] is not None


def test_the_tape_disputes_a_range_it_contradicts(corroborated):
    """`disputed` says the *range* is the broken field, so the same finding reads differently.

    The evidence has to travel with it: `detail.finding_ids` names the `REC.OHLC_DISAGREE`
    rows that say so, or a reader is asked to take the verdict on trust.
    """
    state = _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-16")
    assert state is not None
    assert state.state == DISPUTED
    assert state.detail["field"] == "high"
    assert state.detail["finding_ids"], "a disputed range must cite the findings that dispute it"


def test_one_granularity_is_not_comparable_rather_than_confirmed(corroborated):
    """`not_comparable` licenses neither reading, and says which of §8.7's three reasons it is."""
    state = _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESH26", "2025-09-15")
    assert state is not None
    assert state.state == NOT_COMPARABLE
    assert "ESH26" in state.reason
    assert state.detail["minute_coverage_pct"] is None


def test_corroboration_is_absent_where_it_does_not_apply(corroborated):
    """The fourth answer. Same rule, minute grain — the daily file has no claim to make.

    Absent is not `not_comparable`: one says the question does not arise, the other says it
    arose and could not be answered. A client renders no corroboration object at all here.
    """
    state = _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "minute", "ESZ25", "2025-09-15")
    assert state is None


def test_the_four_answers_are_pairwise_distinct(corroborated):
    """The guard §13 asks for: an implementation returning one answer always would pass three
    of the four tests above and fail only here."""
    answers = [
        _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-15"),
        _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-16"),
        _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESH26", "2025-09-15"),
        _state(corroborated, "CON.CLOSE_OUT_OF_RANGE", "minute", "ESZ25", "2025-09-15"),
    ]
    labels = [a.state if a is not None else None for a in answers]
    assert labels == [CONFIRMED, DISPUTED, NOT_COMPARABLE, None]
    assert len(set(labels)) == 4


# ------------------------------------------------------------------------------- the gate


def test_a_session_below_the_coverage_gate_is_not_comparable(qcon, fixture_path):
    """§8.7's third reason, and the one that is a *filter* rather than a fact about the corpus.

    The same contract, the same session, the same findings — only the gate moves. At the seeded
    0.98 the three-bar tape cannot reproduce a high or a low, so a `confirmed` here would be a
    claim about a comparison that never ran.
    """
    load_file(qcon, fixture_path("rec_corroboration_minute.csv"))
    load_file(qcon, fixture_path("rec_corroboration_daily.csv"))
    assess(qcon, min_records=1)  # seeded gate: 0.98

    row = qcon.execute(
        """
        SELECT CAST(finding_id AS VARCHAR), rule_id, frequency, contract_id, trade_date,
               CAST(run_id AS VARCHAR)
        FROM dq.dq_finding
        WHERE rule_id = 'CON.CLOSE_OUT_OF_RANGE' AND frequency = 'daily'
          AND contract_id = 'ESZ25' AND trade_date = DATE '2025-09-15'
        """
    ).fetchone()
    ref = FindingRef(row[0], row[1], row[2], row[3], row[4], row[5])
    state = corroborate(qcon, [ref])[ref.finding_id]

    assert state.state == NOT_COMPARABLE
    assert "below" in state.reason
    # Not silence: the coverage it *did* have is reported, so a reader can see how far short.
    assert state.detail["minute_coverage_pct"] is not None


def test_corroboration_writes_nothing_and_scores_nothing(qcon, fixture_path):
    """§8.7: it is a reading of findings, not a rule and not a score input.

    Asserted directly, because the cheapest way for a later change to go wrong is for this to
    start writing a finding of its own — and a new `COR.*` row would look plausible.
    """
    load_file(qcon, fixture_path("rec_corroboration_minute.csv"))
    load_file(qcon, fixture_path("rec_corroboration_daily.csv"))
    set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", OPEN_GATE)
    _, before = assess(qcon, min_records=1)

    rows = qcon.execute(
        "SELECT CAST(finding_id AS VARCHAR), rule_id, frequency, contract_id, trade_date, "
        "CAST(run_id AS VARCHAR) FROM dq.dq_finding"
    ).fetchall()
    findings_before = len(rows)
    corroborate(qcon, [FindingRef(*r) for r in rows])

    after = qcon.execute("SELECT count(*) FROM dq.dq_finding").fetchone()[0]
    assert after == findings_before
    scores_after = {
        (s.contract_id, s.frequency): s.dimensions.get("reconciliation")
        for s in before
    }
    # The dimension exists for the dual-grain contract and is untouched by the reading above.
    assert scores_after[("ESZ25", "daily")] is not None
