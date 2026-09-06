"""`REC.*` — the family that needs two files to say anything (spec §8).

Every test here loads a **pair** of fixtures through the real ingest path and runs the real
engine. That is not ceremony: a reconciliation defect does not exist inside either file, so a
single-file fixture would be a fixture for a rule that cannot fire.

Two things these tests are careful about, both from `specs/loupe-solution-design.md` §13.

*Both sides of every filter.* Each fixture pair carries a session that fires and a session that
does not, and both are asserted. A coverage gate, a one-directional volume check and a window
bound are all filters, and one side alone cannot tell a working filter from one that returns
nothing.

*The `frequency` convention is asserted, not assumed.* It is load-bearing — slice 5's
closing-day callout selects `SETTLEMENT_RULES` at `frequency = 'daily'` — so a finding written
on the wrong side is dropped silently rather than failing. Silently is the problem.
"""

from __future__ import annotations

import pytest
from helpers import findings, set_param

from loupe.data import load_file
from loupe.quality import run_rules

REC_RULES = (
    "REC.OHLC_DISAGREE",
    "REC.VOLUME_SHORTFALL",
    "REC.SESSION_ONLY_IN_ONE",
    "REC.CLOSE_CONVENTION",
)

#: The committed fixtures hold three bars a session against a 1,380-slot calendar grid, so the
#: seeded 0.98 gate suppresses every comparison. Tests that want the comparison to happen lower
#: the gate in the seeded row, the way a deployment would; the gate itself is tested separately
#: from both sides.
OPEN_GATE = 0.001


@pytest.fixture
def run_pair(qcon, fixture_path):
    """Load a minute/daily fixture pair and run the reconciliation rules over both."""

    def _run(stem: str, *, coverage: float | None = OPEN_GATE, rule_ids=REC_RULES):
        load_file(qcon, fixture_path(f"{stem}_minute.csv"))
        load_file(qcon, fixture_path(f"{stem}_daily.csv"))
        if coverage is not None:
            set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", coverage)
        return run_rules(qcon, rule_ids=rule_ids, clean=False)

    return _run


# --------------------------------------------------------------- both grains, or nothing


def test_nothing_fires_when_only_one_frequency_is_held(qcon, fixture_path):
    """§8: reconciliation runs only when both granularities exist for the same contract.

    Asserted as an empty result *and* as a successful run: a rule that refused, crashed or was
    skipped would also produce no findings, and those are different outcomes.
    """
    load_file(qcon, fixture_path("rec_ohlc_disagree_minute.csv"))
    set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", OPEN_GATE)
    result = run_rules(qcon, rule_ids=REC_RULES, clean=False)

    assert result.status == "succeeded"
    assert not result.refusals
    assert result.findings_by_rule == {}
    assert set(result.rules_evaluated) == set(REC_RULES)


def test_the_same_contract_with_both_grains_does_fire(run_pair):
    """The other side of the same filter, without which the test above proves nothing."""
    result = run_pair("rec_ohlc_disagree")
    assert result.findings_by_rule.get("REC.OHLC_DISAGREE") == 1


# ------------------------------------------------------------------------ OHLC disagreement


def test_ohlc_disagreement_names_the_field_and_its_evidence(qcon, run_pair):
    result = run_pair("rec_ohlc_disagree")
    (found,) = findings(qcon, result.run_id, "REC.OHLC_DISAGREE")

    assert found["trade_date"].isoformat() == "2025-09-15"
    assert found["severity"] == "error"
    assert found["details"]["field"] == "high"
    assert found["details"]["vendor"] == 6602.50
    assert found["details"]["derived"] == 6602.00
    assert found["details"]["difference_ticks"] == 2.0
    # The session with no defect is silent, so the rule is selecting rather than reporting
    # everything it compared.
    assert found["record_id"] is None, "session-scoped: the subject is the session, not a row"


def test_a_disagreement_is_a_statement_about_the_daily_file(qcon, run_pair):
    """The `frequency` convention of §8, asserted because breaking it fails silently.

    `REC.OHLC_DISAGREE` says the vendor's stated high is wrong, so it is a statement about the
    **daily** side and the tape is what it was checked against. Written the other way round it
    would vanish from the Risk closing-day callout, which filters at `frequency = 'daily'`
    (§11.6), without any test failing.
    """
    result = run_pair("rec_ohlc_disagree")
    (found,) = findings(qcon, result.run_id, "REC.OHLC_DISAGREE")
    assert found["frequency"] == "daily"
    assert found["compare_frequency"] == "minute"


def test_the_coverage_gate_suppresses_and_admits(qcon, fixture_path):
    """§8.1: gated on the **calendar's** expected slots, not on a maximum inferred from the file.

    Both sides in one test, because they are the same filter. The fixture holds three bars of a
    1,380-slot session, so it is far below the seeded 0.98 and comfortably above 0.001.
    """
    load_file(qcon, fixture_path("rec_ohlc_disagree_minute.csv"))
    load_file(qcon, fixture_path("rec_ohlc_disagree_daily.csv"))

    shut = run_rules(qcon, rule_ids=("REC.OHLC_DISAGREE",), clean=False)
    assert shut.findings_by_rule == {}, "the seeded 0.98 gate must suppress a 3-bar session"

    set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", OPEN_GATE)
    open_ = run_rules(qcon, rule_ids=("REC.OHLC_DISAGREE",), clean=False)
    assert open_.findings_by_rule == {"REC.OHLC_DISAGREE": 1}


def test_the_tolerance_comes_from_the_seeded_row(qcon, fixture_path):
    """A threshold the runner carried as a literal would not move when the row does."""
    load_file(qcon, fixture_path("rec_ohlc_disagree_minute.csv"))
    load_file(qcon, fixture_path("rec_ohlc_disagree_daily.csv"))
    set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", OPEN_GATE)
    # The disagreement is two ticks; three ticks of tolerance must swallow it.
    set_param(qcon, "REC.OHLC_DISAGREE", "tolerance_ticks", 3)
    assert run_rules(qcon, rule_ids=("REC.OHLC_DISAGREE",), clean=False).findings_by_rule == {}


# ---------------------------------------------------------------------- volume, one direction


def test_volume_shortfall_fires_only_downwards(qcon, run_pair):
    """§8.3. The fixture holds a session short by 20% and one that exceeds the vendor by 5%.

    Excess is ordinary: block and privately negotiated trades are reported to the exchange
    without ever crossing the tape (`specs/sample-corpus.md` §6.4). Only the shortfall fires,
    and the excess session's silence is what makes that a direction rather than a coincidence.
    """
    result = run_pair("rec_volume_shortfall")
    found = findings(qcon, result.run_id, "REC.VOLUME_SHORTFALL")

    assert [f["trade_date"].isoformat() for f in found] == ["2025-09-15"]
    assert found[0]["details"]["ratio"] == 0.8
    assert found[0]["details"]["shortfall"] == 400


def test_a_shortfall_is_a_statement_about_the_tape(qcon, run_pair):
    """The other half of the §8 convention, and the reason §8.3 is one-directional.

    The claim is that the *minute* side is short, so `frequency` is `minute` — the opposite
    side from `REC.OHLC_DISAGREE`, which is what makes this worth asserting separately.
    """
    result = run_pair("rec_volume_shortfall")
    (found,) = findings(qcon, result.run_id, "REC.VOLUME_SHORTFALL")
    assert found["frequency"] == "minute"
    assert found["compare_frequency"] == "daily"


def test_the_shortfall_threshold_comes_from_the_seeded_row(qcon, run_pair):
    """Widening `max_shortfall_pct` past the fixture's 20% gap must silence it."""
    result = run_pair("rec_volume_shortfall", rule_ids=("REC.VOLUME_SHORTFALL",))
    assert result.findings_by_rule == {"REC.VOLUME_SHORTFALL": 1}

    set_param(qcon, "REC.VOLUME_SHORTFALL", "max_shortfall_pct", 0.5)
    widened = run_rules(qcon, rule_ids=("REC.VOLUME_SHORTFALL",), clean=False)
    assert widened.findings_by_rule == {}


# ------------------------------------------------------------------------ session only in one


def test_session_only_in_one_reports_both_directions_differently(qcon, run_pair):
    """§8.5. Two directions, two severities, two sides — none of them interchangeable.

    A minute session with no daily row says the tape traded and no settlement was published:
    a `warning`, on the minute side. A daily row with no minute session is the ordinary
    deferred-contract case and drops to `params.absent_daily_severity`, on the daily side.
    """
    result = run_pair("rec_session_only_in_one")
    found = {f["trade_date"].isoformat(): f for f in findings(
        qcon, result.run_id, "REC.SESSION_ONLY_IN_ONE"
    )}

    assert sorted(found) == ["2025-09-16", "2025-09-17"]

    minute_only = found["2025-09-16"]
    assert (minute_only["frequency"], minute_only["compare_frequency"]) == ("minute", "daily")
    assert minute_only["severity"] == "warning"

    daily_only = found["2025-09-17"]
    assert (daily_only["frequency"], daily_only["compare_frequency"]) == ("daily", "minute")
    assert daily_only["severity"] == "info"


def test_absence_outside_the_reconcilable_window_is_not_a_finding(qcon, run_pair):
    """§8.5: the window is the intersection of the two spans, and outside it absence is normal.

    The fixture's minute file runs four sessions past the end of its daily file. The last of
    them is minute-only exactly like 2025-09-16 is, and it must stay silent — otherwise every
    contract whose two files end on different days reports its whole tail as broken.
    """
    result = run_pair("rec_session_only_in_one")
    days = {
        f["trade_date"].isoformat()
        for f in findings(qcon, result.run_id, "REC.SESSION_ONLY_IN_ONE")
    }
    assert "2025-09-22" not in days
    assert days, "the in-window direction must fire, or this asserts nothing"


# ------------------------------------------------------------------------- close convention


def test_a_settlement_shaped_difference_is_info_and_not_an_error(qcon, run_pair):
    """§8.4. The vendor close sits nearer the settlement mark than the session end.

    That is what a settlement looks like beside a last trade, so it is reported and never
    scored: `info` keeps it out of every numerator (§11.1) and out of the closing-day callout
    (§11.6), which is the one column that must not carry an expected difference.
    """
    result = run_pair("rec_close_convention")
    found = findings(qcon, result.run_id, "REC.CLOSE_CONVENTION")

    assert [f["trade_date"].isoformat() for f in found] == ["2025-09-15"]
    assert found[0]["severity"] == "info"
    assert found[0]["frequency"] == "daily", "its subject is the settlement"
    assert found[0]["details"]["settlement_signature"] is True
    assert found[0]["details"]["close_at_mark"] == 6601.25
    assert found[0]["details"]["mark_gap_minutes"] == 0.0


def test_a_close_with_no_settlement_signature_is_a_disagreement(qcon, run_pair):
    """The other branch of the same difference, and the reason both rules read one mark.

    On 2025-09-16 the vendor close is *further* from the 15:00 mark than from the session end,
    so §8.4's explanation does not apply and the difference is `REC.OHLC_DISAGREE` on `close` —
    an error rather than an info. The two branches are exclusive, which is asserted by the two
    sessions landing on different rules.
    """
    result = run_pair("rec_close_convention")
    convention = {f["trade_date"].isoformat() for f in findings(
        qcon, result.run_id, "REC.CLOSE_CONVENTION"
    )}
    disagreements = {
        f["trade_date"].isoformat(): f
        for f in findings(qcon, result.run_id, "REC.OHLC_DISAGREE")
        if f["details"]["field"] == "close"
    }

    assert convention == {"2025-09-15"}
    assert set(disagreements) == {"2025-09-16"}
    assert disagreements["2025-09-16"]["severity"] == "error"
    assert disagreements["2025-09-16"]["details"]["settlement_signature"] is False


def test_an_unknown_tick_is_compared_exactly_and_says_so(qcon, run_pair):
    """§8.2: where no tick is known the comparison is exact **and the finding records it**.

    The ES daily `close` is settlement-bearing, so `ref.tick` carries no lattice for it. A
    finding that compared exactly without saying so would be indistinguishable from one
    compared at a seeded tolerance.
    """
    result = run_pair("rec_close_convention")
    close = next(
        f for f in findings(qcon, result.run_id, "REC.OHLC_DISAGREE")
        if f["details"]["field"] == "close"
    )
    assert close["details"]["tick_size"] is None
    assert close["details"]["comparison"] == "exact"


def test_the_mark_is_read_from_one_row_by_both_rules(qcon, run_pair, fixture_path):
    """§8.4's mark lives on `REC.CLOSE_CONVENTION` and `REC.OHLC_DISAGREE` reads it there.

    Moving it to an hour the fixture's bars cannot reach makes the mark unresolvable, and then
    *neither* close finding fires — not one of each. That is the deliberate reading: an
    unresolvable mark cannot tell an expected settlement difference from an error, and guessing
    would accuse a settlement of being wrong for behaving like one.
    """
    load_file(qcon, fixture_path("rec_close_convention_minute.csv"))
    load_file(qcon, fixture_path("rec_close_convention_daily.csv"))
    set_param(qcon, "REC.OHLC_DISAGREE", "min_coverage_pct", OPEN_GATE)
    set_param(qcon, "REC.CLOSE_CONVENTION", "settlement_mark_local", {"default": "03:00"})

    result = run_rules(
        qcon, rule_ids=("REC.CLOSE_CONVENTION", "REC.OHLC_DISAGREE"), clean=False
    )
    assert result.findings_by_rule.get("REC.CLOSE_CONVENTION") is None
    close_findings = [
        f for f in findings(qcon, result.run_id, "REC.OHLC_DISAGREE")
        if f["details"]["field"] == "close"
    ]
    assert close_findings == []
