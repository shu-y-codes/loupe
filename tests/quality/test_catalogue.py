"""The catalogue, the seeder, and the parity that keeps them honest.

The parity test is the one that earns its place. Without it, a catalogue entry with no runner
seeds a rule that silently never fires, and a runner with no entry is dead code — and both
failures are invisible at run time, because a rule that finds nothing and a rule that never
ran produce the same empty result.
"""

from __future__ import annotations

import json

import pytest

from loupe.quality import (
    CATALOGUE,
    REGISTRY,
    RULES_ENFORCED_BY_ENGINE,
    SCORE_WEIGHTS,
    RulesNotSeeded,
    ruleset_hash,
    run_rules,
    seed_quality,
    seed_rules,
)
from loupe.quality.catalogue import CATALOGUE_BY_ID, TRIAGE_WEIGHT_BY_SEVERITY

# specs/dq-rules-and-scoring.md §15.1 plus §8's `REC.*` table, less `UNQ.DUPLICATE_FILE`,
# which ingest enforces.
# Written out rather than imported so that this test compares the code against the spec and
# not against itself. The three rules plans/02-quality.md deferred to slice 3
# (`CON.DERIVED_BAR_INVALID` and the `OUT.*` pair) landed with the bar writer and the MAD
# method, so they are in scope here now.
SPEC_IN_SCOPE = frozenset(
    {
        "CMP.NULL_FIELD",
        "CMP.MISSING_TIMESTAMP",
        "CMP.SESSION_MISSING",
        "CMP.PARTIAL_SESSION",
        "CMP.SPARSE_SERIES",
        "UNQ.EXACT_DUPLICATE",
        "UNQ.KEY_CONFLICT",
        "VAL.NON_POSITIVE_PRICE",
        "VAL.NEGATIVE_VOLUME",
        "VAL.NON_INTEGER_VOLUME",
        "VAL.OFF_TICK_PRICE",
        "VAL.ZERO_VOLUME_WITH_RANGE",
        "VAL.PRICE_MAGNITUDE",
        "VAL.EXTREME_VOLUME",
        "CON.HIGH_LT_LOW",
        "CON.OPEN_OUT_OF_RANGE",
        "CON.CLOSE_OUT_OF_RANGE",
        "CON.WEEKEND_RECORD",
        "CON.RECORD_IN_HALT",
        "CON.RECORD_ON_HOLIDAY",
        "CON.STALE_REPEAT",
        "CON.PRICE_JUMP",
        "TIM.OUT_OF_ORDER",
        "TIM.FUTURE_TIMESTAMP",
        "TIM.BEFORE_LISTING",
        "TIM.AFTER_EXPIRY",
        "TIM.OFF_GRID",
        "TIM.TIMEZONE_MISALIGNED",
        "ROL.THIN_NEAR_EXPIRY",
        "ROL.NO_SUCCESSOR",
        # Slice 6. §15.1 is slice 2's list and does not name them; the four IDs are §8's own
        # table, which is where the `REC.*` family is specified, and §15 defers only their
        # *fixtures* to this slice ("`REC.*` fixtures wait for slice 6").
        "REC.OHLC_DISAGREE",
        "REC.VOLUME_SHORTFALL",
        "REC.SESSION_ONLY_IN_ONE",
        "REC.CLOSE_CONVENTION",
        "CON.DERIVED_BAR_INVALID",
        "OUT.RETURN_MAD",
        "OUT.VOLUME_MAD",
    }
)

#: Slice 2 deferred these three for want of `specs/analytics-semantics.md`; slice 3 promoted
#: the spec and landed them. Kept as a named empty set rather than deleted: it is the seam the
#: parity test watches, and a future deferral should reuse it rather than reinvent it.
DEFERRED_TO_SLICE_3: frozenset[str] = frozenset()


# ------------------------------------------------------------------------------- parity


def test_catalogue_runners_and_spec_are_the_same_set():
    assert set(REGISTRY) == RULES_ENFORCED_BY_ENGINE
    assert RULES_ENFORCED_BY_ENGINE == SPEC_IN_SCOPE


def test_duplicate_file_is_the_only_rule_without_a_runner():
    without = {spec.rule_id for spec in CATALOGUE} - RULES_ENFORCED_BY_ENGINE
    assert without == {"UNQ.DUPLICATE_FILE"}
    assert CATALOGUE_BY_ID["UNQ.DUPLICATE_FILE"].enforced_at == "ingest"


def test_nothing_is_deferred_any_more():
    """The slice-2 deferral is spent: every in-scope rule now has a row and a runner."""
    assert not DEFERRED_TO_SLICE_3
    assert {"CON.DERIVED_BAR_INVALID", "OUT.RETURN_MAD", "OUT.VOLUME_MAD"} <= set(REGISTRY)


def test_every_in_scope_rule_has_a_fixture(fixture_path):
    """Spec §15: `tests/fixtures/<rule_id_lower>.csv`, with `.` becoming `_`.

    Two rules reuse the ingest fixtures the spec already assigns them: `CMP.NULL_FIELD` reads
    `null_fields.csv`, and `CON.WEEKEND_RECORD`'s negative case is `weekend_sunday_evening.csv`.

    `REC.*` takes a **pair**, and it has to. One file cannot carry a cross-frequency defect:
    the rule compares a minute tape against the daily file that claims to summarise it, so the
    fixture is `<rule>_minute.csv` and `<rule>_daily.csv` and a single file would be a fixture
    for a rule that cannot fire.
    """
    reused = {"CMP.NULL_FIELD": "null_fields.csv"}
    for rule_id in sorted(SPEC_IN_SCOPE):
        stem = rule_id.lower().replace(".", "_")
        if rule_id.startswith("REC."):
            fixture_path(f"{stem}_minute.csv")
            fixture_path(f"{stem}_daily.csv")
            continue
        fixture_path(reused.get(rule_id, stem + ".csv"))


def test_every_rule_id_is_unique():
    ids = [spec.rule_id for spec in CATALOGUE]
    assert len(ids) == len(set(ids))


def test_every_dimension_is_one_of_the_six():
    six = {
        "completeness",
        "uniqueness",
        "validity",
        "consistency",
        "timeliness",
        "reconciliation",
    }
    assert {spec.dimension for spec in CATALOGUE} <= six


def test_roll_rules_sit_in_completeness_and_are_info():
    """§1: `ROL.*` use the completeness dimension because they exist to suppress its noise."""
    for rule_id in ("ROL.THIN_NEAR_EXPIRY", "ROL.NO_SUCCESSOR"):
        spec = CATALOGUE_BY_ID[rule_id]
        assert spec.dimension == "completeness"
        assert spec.severity == "info"


# -------------------------------------------------------------------------------- seeding


def test_seed_writes_every_catalogue_rule(con):
    report = seed_quality(con)
    assert report.inserted == len(CATALOGUE)
    assert report.weights == len(SCORE_WEIGHTS)
    seeded = {
        row[0]
        for row in con.execute(
            "SELECT rule_id FROM dq.dq_rule WHERE origin = 'builtin'"
        ).fetchall()
    }
    assert seeded == {spec.rule_id for spec in CATALOGUE}


def test_triage_weight_is_seeded_from_severity(con):
    seed_quality(con)
    rows = con.execute("SELECT severity, triage_weight FROM dq.dq_rule").fetchall()
    for severity, weight in rows:
        assert weight == pytest.approx(TRIAGE_WEIGHT_BY_SEVERITY[severity])


def test_score_weights_match_the_spec(con):
    seed_quality(con)
    seeded = dict(con.execute("SELECT dimension, weight FROM dq.score_weight").fetchall())
    assert seeded == pytest.approx(dict(SCORE_WEIGHTS))


def test_reseeding_an_unchanged_catalogue_changes_nothing(con):
    seed_quality(con)
    before = con.execute(
        "SELECT rule_id, CAST(params AS VARCHAR), severity, triage_weight, enabled "
        "FROM dq.dq_rule ORDER BY rule_id"
    ).fetchall()

    report = seed_quality(con)
    assert report.inserted == 0
    assert report.refreshed == len(CATALOGUE)

    after = con.execute(
        "SELECT rule_id, CAST(params AS VARCHAR), severity, triage_weight, enabled "
        "FROM dq.dq_rule ORDER BY rule_id"
    ).fetchall()
    assert after == before


def test_reseed_refreshes_a_locally_changed_default(con):
    """A corrected catalogue default must reach a database that already exists (§17)."""
    seed_quality(con)
    con.execute(
        "UPDATE dq.dq_rule SET params = ?, severity = 'info' WHERE rule_id = ?",
        [json.dumps({"threshold": 0.01}), "CMP.PARTIAL_SESSION"],
    )
    seed_rules(con)
    params, severity = con.execute(
        "SELECT CAST(params AS VARCHAR), severity FROM dq.dq_rule WHERE rule_id = ?",
        ["CMP.PARTIAL_SESSION"],
    ).fetchone()
    assert json.loads(params)["threshold"] == 0.95
    assert severity == "warning"


def test_reseed_leaves_a_user_authored_rule_untouched(con):
    """The extensibility seam: the refresh is guarded `WHERE origin = 'builtin'`.

    Nothing in v1 writes a non-builtin rule, so without this test the guard is untested code
    that will have rotted by the time suggestion-apply needs it.
    """
    seed_quality(con)
    con.execute(
        """
        INSERT INTO dq.dq_rule
          (rule_id, dimension, name, description, severity, scope, params, triage_weight,
           origin)
        VALUES ('VAL.HOUSE_RULE', 'validity', 'House rule', 'desk-specific', 'warning',
                'record', '{"threshold": 7}', 99.0, 'user')
        """
    )
    report = seed_quality(con)

    assert report.skipped_foreign == 0  # a user rule is not in the catalogue at all
    row = con.execute(
        "SELECT severity, triage_weight, CAST(params AS VARCHAR), origin "
        "FROM dq.dq_rule WHERE rule_id = 'VAL.HOUSE_RULE'"
    ).fetchone()
    assert row == ("warning", 99.0, '{"threshold": 7}', "user")


def test_reseed_skips_a_catalogue_id_someone_else_now_owns(con):
    """If a non-builtin row takes a catalogue ID, the seeder reports it rather than stamping it."""
    seed_quality(con)
    con.execute("UPDATE dq.dq_rule SET origin = 'user', severity = 'info' WHERE rule_id = ?",
                ["VAL.NEGATIVE_VOLUME"])
    report = seed_quality(con)
    assert report.skipped_foreign == 1
    assert con.execute(
        "SELECT severity FROM dq.dq_rule WHERE rule_id = 'VAL.NEGATIVE_VOLUME'"
    ).fetchone() == ("info",)


def test_a_deleted_builtin_rule_comes_back(con):
    """Disabling is `enabled = FALSE`, never a delete — so a delete is repaired on re-seed."""
    seed_quality(con)
    con.execute("DELETE FROM dq.dq_rule WHERE rule_id = 'VAL.NEGATIVE_VOLUME'")
    report = seed_quality(con)
    assert report.inserted == 1
    assert con.execute(
        "SELECT count(*) FROM dq.dq_rule WHERE rule_id = 'VAL.NEGATIVE_VOLUME'"
    ).fetchone() == (1,)


def test_disabling_survives_a_reseed(con):
    """`enabled` is operator state, not a catalogue value; resetting it would make the
    documented disable seam a lie."""
    seed_quality(con)
    con.execute("UPDATE dq.dq_rule SET enabled = FALSE WHERE rule_id = 'VAL.NEGATIVE_VOLUME'")
    seed_quality(con)
    assert con.execute(
        "SELECT enabled FROM dq.dq_rule WHERE rule_id = 'VAL.NEGATIVE_VOLUME'"
    ).fetchone() == (False,)


def test_a_disabled_rule_does_not_run(qcon, run_fixture):
    qcon.execute("UPDATE dq.dq_rule SET enabled = FALSE WHERE rule_id = 'VAL.NEGATIVE_VOLUME'")
    _, result = run_fixture("val_negative_volume.csv")
    assert "VAL.NEGATIVE_VOLUME" not in result.rules_evaluated
    assert "VAL.NEGATIVE_VOLUME" not in result.findings_by_rule


# --------------------------------------------------------------------------- ruleset hash


def test_ruleset_hash_is_stable_across_reseeds(con):
    seed_quality(con)
    first = ruleset_hash(con)
    seed_quality(con)
    assert ruleset_hash(con) == first


def test_ruleset_hash_moves_when_a_threshold_moves(con):
    seed_quality(con)
    before = ruleset_hash(con)
    con.execute(
        "UPDATE dq.dq_rule SET params = ? WHERE rule_id = 'CMP.PARTIAL_SESSION'",
        [json.dumps({"threshold": 0.5})],
    )
    assert ruleset_hash(con) != before


def test_ruleset_hash_moves_when_a_rule_is_disabled(con):
    seed_quality(con)
    before = ruleset_hash(con)
    con.execute("UPDATE dq.dq_rule SET enabled = FALSE WHERE rule_id = 'CON.PRICE_JUMP'")
    assert ruleset_hash(con) != before


def test_the_run_records_the_hash_and_the_scope(qcon, run_fixture):
    batch, result = run_fixture("val_negative_volume.csv")
    row = qcon.execute(
        "SELECT batch_id, ruleset_hash, CAST(scope_filter AS VARCHAR), status, findings_count "
        "FROM dq.dq_run WHERE run_id = ?",
        [result.run_id],
    ).fetchone()
    assert str(row[0]) == batch.batch_id
    assert row[1] == result.ruleset_hash == ruleset_hash(qcon)
    assert json.loads(row[2])["batch_id"] == batch.batch_id
    assert row[3] == "succeeded"
    assert row[4] == result.findings_count


def test_running_without_a_seeded_catalogue_raises(con):
    with pytest.raises(RulesNotSeeded):
        run_rules(con)
