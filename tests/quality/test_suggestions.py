"""Suggestions — report-only, with a rationale and a dry-run effect (spec §13).

Two properties carry the weight here.

*The payload has no way to act.* v1 identifies and suggests; it does not mutate (locked
decision 10). That is asserted as the **absence** of any apply, dismiss or action key from the
serialised shape, because the shipped failure mode is not a broken button — it is a key that
tempts a client into rendering one.

*The rationale is the evidence in words.* A suggestion whose text does not carry the numbers
behind it is an opinion, and this release has no mechanism for the reader to check an opinion.
"""

from __future__ import annotations

import pytest

from loupe.data import load_file
from loupe.quality import assess
from loupe.quality.patterns import find_patterns
from loupe.quality.suggestions import suggest


@pytest.fixture
def settlement(qcon, fixture_path):
    """24 sessions whose vendor close sits at the settlement mark, not at the last trade.

    The corpus's own shape: `REC.CLOSE_CONVENTION` firing on nearly every reconcilable session
    is not a defect, it is the daily file telling you what its `close` column means (§13).
    """
    load_file(qcon, fixture_path("insights_pattern_settlement_minute.csv"))
    load_file(qcon, fixture_path("insights_pattern_settlement_daily.csv"))
    assess(qcon, min_records=1)
    return qcon


def test_a_settlement_convention_produces_its_suggestion(settlement):
    """The generator, end to end, from findings the real engine wrote."""
    (found,) = suggest(settlement)

    assert found.kind == "ingest"
    assert "settlement" in found.title.lower()
    assert found.proposed_change["target"] == "stage.ingest_batch"
    assert found.proposed_change["operation"] == "set_close_convention"
    assert found.proposed_change["params"]["close_convention"] == "settlement"


def test_the_rationale_carries_the_numbers_behind_it(settlement):
    (found,) = suggest(settlement)
    assert "24 sessions" in found.rationale
    assert "settlement mark" in found.rationale
    assert found.evidence["findings"] == 24
    assert found.evidence["lift"] == pytest.approx(4.0)
    assert found.evidence["rule_id"] == "REC.CLOSE_CONVENTION"


def test_every_suggestion_cites_a_pattern_that_still_exists(settlement):
    """`from_pattern` is only useful if the next call produces the same id."""
    ids = {p.pattern_id for p in find_patterns(settlement)}
    for found in suggest(settlement):
        assert found.from_pattern in ids


def test_the_expected_effect_is_a_dry_run_and_says_so(settlement):
    """§13: computed by dry-running the change before display — over persisted metrics.

    A read endpoint that re-ran the rules to answer this would be a report that writes, so the
    basis is stated on the payload rather than left for a reader to assume.
    """
    (found,) = suggest(settlement)
    assert found.expected_effect["findings_suppressed"] == 24
    assert "no rules were re-run" in found.expected_effect["basis"]


def test_an_info_rule_says_applying_it_moves_no_score(settlement):
    """`REC.CLOSE_CONVENTION` is `info` and in no numerator (§11.1), so nothing improves.

    Without this the effect reads as "24 findings suppressed" and implies a score gain that
    cannot happen — the change retires a report, which is worth doing for a different reason.
    """
    (found,) = suggest(settlement)
    assert "none" in found.expected_effect["score_impact"]
    assert "score" in found.expected_effect["score_impact"]


def test_the_payload_exposes_no_apply_or_dismiss_path(settlement):
    """Report-only, asserted as absence over the whole serialised shape.

    Not just a missing `actions` key: any key or value that names an action would be enough for
    a client to build a control on, so the search is over the JSON as text.
    """
    for found in suggest(settlement):
        payload = found.as_json()
        assert "actions" not in payload
        assert not [k for k in payload if k in {"apply", "dismiss", "links", "href", "url"}]
        rendered = repr(payload).lower()
        for word in ("apply", "dismiss", "/insights/suggestions/"):
            assert word not in rendered, f"{word!r} in a report-only payload"


def test_one_pattern_yields_at_most_one_suggestion(settlement):
    """Two proposals for one piece of evidence ask the reader to choose with nothing to
    choose on. The settlement rule also concentrates in the hour around the mark, so this is a
    live collision rather than a hypothetical one."""
    patterns = find_patterns(settlement)
    assert len({p.dimension for p in patterns}) > 1, "the collision must exist to be tested"
    found = suggest(settlement)
    assert len(found) == len({s.suggestion_id for s in found})
    assert len({s.proposed_change["operation"] for s in found}) == len(found)


def test_no_patterns_means_no_suggestions(qcon):
    assert suggest(qcon) == []


def test_suggestions_can_be_generated_from_patterns_already_computed(settlement):
    """The API serves both reports from one request path; recomputing risks two answers."""
    patterns = find_patterns(settlement)
    assert suggest(settlement, patterns=patterns) == suggest(settlement)
