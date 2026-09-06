"""Injection — labelled defects, and a manifest a test can fail against (done-when 5).

The demo strategy leads with **real** findings; injection exists for the defect types this
corpus happens not to contain (`specs/loupe-solution-design.md` §9). What makes that a test
asset rather than a demo prop is the manifest: it names the rule each defect should trip, so
these tests run the real engine over the injected file and assert the labels and the findings
agree. A prop only has to look wrong; this has to be wrong in a stated way.

The base is a committed fixture rather than a fetched sample, so the tier runs in CI. The
utility's contract is the same either way — read one file, write another, label everything.
"""

from __future__ import annotations

import json

import pytest

from loupe.data import load_file
from loupe.demo import inject, load_manifest
from loupe.demo.injection import INJECTABLE_RULES, RefusedToOverwrite
from loupe.quality import run_rules

BASE = "injection_base.csv"


@pytest.fixture
def injected(tmp_path, fixture_path):
    """One injected copy and its manifest, from the clean committed base."""
    return inject(fixture_path(BASE), tmp_path / "injected.csv")


# ------------------------------------------------------------ never corrupt the source


def test_the_source_file_is_left_untouched(injected, fixture_path):
    """The rule this module exists to keep. A corrupted sample nobody labelled is
    indistinguishable from a vendor defect, and it would end up quoted in a spec."""
    import hashlib

    before = hashlib.sha256(fixture_path(BASE).read_bytes()).hexdigest()
    assert injected.manifest.source_sha256 == before
    assert injected.output_path != fixture_path(BASE)


def test_writing_over_the_source_is_refused(tmp_path, fixture_path):
    """Refused, not resolved: once the two are one file nobody can tell manufactured numbers
    from measured ones."""
    source = fixture_path(BASE)
    with pytest.raises(RefusedToOverwrite):
        inject(source, source)


def test_a_base_too_small_to_carry_the_defects_is_refused(tmp_path):
    """Overlapping sites would make a finding unattributable to the label claiming it."""
    tiny = tmp_path / "tiny.csv"
    tiny.write_text(
        "contract,timestamp,open,high,low,close,volume\n"
        "ESZ25,2025-09-15 09:00:00,1,2,0.5,1.5,10\n"
    )
    with pytest.raises(ValueError, match="at least 40"):
        inject(tiny, tmp_path / "out.csv")


# ------------------------------------------------------------------------- the manifest


def test_every_injectable_rule_is_planted_and_labelled(injected):
    """`INJECTABLE_RULES` is a claim, so the manifest has to keep it.

    Without this a site shortage would silently drop the last injector and the utility would
    advertise a defect type it never plants.
    """
    assert injected.manifest.rule_ids == INJECTABLE_RULES


def test_the_manifest_round_trips(injected):
    assert load_manifest(injected.manifest_path).as_json() == injected.manifest.as_json()


def test_the_manifest_is_written_beside_the_file_and_not_inside_it(injected):
    """Labels are not data. A file carrying its own answer key would be loaded with it."""
    assert injected.manifest_path != injected.output_path
    text = injected.output_path.read_text()
    assert "__uid" not in text
    assert "rule_id" not in text
    header = text.splitlines()[0].split(",")
    assert header == ["contract", "timestamp", "open", "high", "low", "close", "volume"]


def test_injection_is_deterministic(tmp_path, fixture_path):
    """A demo rehearsed on Monday is the demo given on Friday."""
    first = inject(fixture_path(BASE), tmp_path / "a.csv")
    second = inject(fixture_path(BASE), tmp_path / "b.csv")
    assert first.manifest.output_sha256 == second.manifest.output_sha256
    assert [d.as_json() for d in first.manifest.defects] == [
        d.as_json() for d in second.manifest.defects
    ]


def test_a_different_seed_produces_a_different_file(tmp_path, fixture_path):
    """The other side: deterministic means *given the seed*, not fixed forever."""
    first = inject(fixture_path(BASE), tmp_path / "a.csv")
    other = inject(fixture_path(BASE), tmp_path / "b.csv", seed=1)
    assert first.manifest.output_sha256 != other.manifest.output_sha256


def test_one_rule_can_be_planted_on_its_own(tmp_path, fixture_path):
    """So a demo can show one defect end to end without eight others on the screen."""
    report = inject(
        fixture_path(BASE), tmp_path / "one.csv", rules=("VAL.NEGATIVE_VOLUME",)
    )
    assert report.manifest.rule_ids == {"VAL.NEGATIVE_VOLUME"}


# -------------------------------------------------------- ground truth against the engine


@pytest.fixture
def engine_findings(qcon, injected):
    """The real rule engine over the injected file, indexed by rule and source row."""
    batch = load_file(qcon, injected.output_path)
    result = run_rules(qcon, batch_id=batch.batch_id, clean=False)
    rows = qcon.execute(
        """
        SELECT f.rule_id, m.source_row
        FROM dq.dq_finding f
        LEFT JOIN stage.market_record m ON m.record_id = f.record_id
        WHERE f.run_id = ?
        """,
        [result.run_id],
    ).fetchall()
    by_rule: dict[str, set[int | None]] = {}
    for rule_id, source_row in rows:
        by_rule.setdefault(rule_id, set()).add(source_row)
    return result, by_rule


def test_every_labelled_row_defect_is_found_at_the_row_the_manifest_names(
    injected, engine_findings
):
    """The manifest's `source_row` is the same coordinate a finding cites, so they can be
    compared directly. A label pointing at an innocent row is worse than no label.

    Session-scoped defects are excluded here and checked below: a run of missing slots has no
    `record_id` because there is no record — the defect *is* the absence.
    """
    _, by_rule = engine_findings
    row_shaped = [d for d in injected.manifest.defects if d.rule_id != "CMP.MISSING_TIMESTAMP"]
    assert len(row_shaped) == len(INJECTABLE_RULES) - 1

    for defect in row_shaped:
        found = by_rule.get(defect.rule_id, set())
        assert defect.source_row in found, (
            f"{defect.rule_id} labelled at output row {defect.source_row}; "
            f"the engine found it at {sorted(r for r in found if r)}"
        )


def test_the_injected_gap_is_found_as_one_run_at_its_labelled_timestamp(
    qcon, injected, engine_findings
):
    """The absence-shaped defect, matched by the span it covers rather than by a row.

    One finding, not five: `CMP.MISSING_TIMESTAMP` run-length-encodes a gap, which is what
    keeps a 1,380-slot outage from becoming 1,380 findings.

    The manifest's timestamp is the source label — exchange wall clock, exactly as the file
    carries it — while the finding's is UTC, so the comparison converts. Comparing them raw
    would silently match the ambient gap either side of the fixture's short block and pass
    against an injector that deleted nothing.
    """
    result, _ = engine_findings
    gap = next(d for d in injected.manifest.defects if d.rule_id == "CMP.MISSING_TIMESTAMP")

    runs = qcon.execute(
        """
        SELECT affected_rows,
               strftime(ts_start_utc AT TIME ZONE 'America/Chicago', '%Y-%m-%d %H:%M:%S')
        FROM dq.dq_finding
        WHERE run_id = ? AND rule_id = 'CMP.MISSING_TIMESTAMP'
        """,
        [result.run_id],
    ).fetchall()

    five_slot = [row for row in runs if row[0] == 5]
    assert len(five_slot) == 1, f"expected one five-slot run among {sorted(r[0] for r in runs)}"
    assert five_slot[0][1] == gap.timestamp
    # The ambient runs are the fixture's short block inside a full session, and they are much
    # larger — which is what makes the five-slot run attributable to the injection.
    assert max(row[0] for row in runs) > 5


def test_the_clean_base_produces_none_of_the_injected_defects(qcon, fixture_path):
    """The control, and the reason the assertions above mean anything.

    If the base already tripped these rules, every test in this file would pass against an
    injector that did nothing at all.
    """
    batch = load_file(qcon, fixture_path(BASE))
    result = run_rules(qcon, batch_id=batch.batch_id, clean=False)
    fired = set(result.findings_by_rule)
    assert not (fired & INJECTABLE_RULES - {"CMP.MISSING_TIMESTAMP"}), (
        f"the base fixture is not clean: {sorted(fired & INJECTABLE_RULES)}"
    )


def test_the_manifest_is_readable_json_with_the_labels_a_reader_needs(injected):
    """It is evidence for a human as much as for a test: the rule, the row, and both values."""
    payload = json.loads(injected.manifest_path.read_text())
    assert payload["rows_in"] and payload["rows_out"]
    for defect in payload["defects"]:
        assert defect["rule_id"] and defect["kind"] and defect["note"]
        assert defect["source_row"] >= 1
