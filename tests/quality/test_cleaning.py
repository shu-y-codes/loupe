"""Default cleaning: raw records stay immutable, decisions are rows, the clean view is derived.

Default cleaning is automatic policy, not a user action. "Report-only" in v1 bounds what a
*user* may do to rules and findings; it does not mean the engine declines to clean.
"""

from __future__ import annotations

from helpers import findings, source_rows


def excluded_source_rows(con) -> list[int]:
    return [
        int(row[0])
        for row in con.execute(
            """
            SELECT r.source_row
            FROM stage.market_record r
            JOIN dq.cleaning_action a ON a.record_id = r.record_id
            WHERE a.action IN ('exclude', 'dedupe_drop')
            ORDER BY r.source_row
            """
        ).fetchall()
    ]


def clean_source_rows(con) -> list[int]:
    return [
        int(row[0])
        for row in con.execute(
            "SELECT source_row FROM dq.market_record_clean ORDER BY source_row"
        ).fetchall()
    ]


def test_an_error_finding_excludes_its_record(qcon, run_fixture):
    _, result = run_fixture("con_high_lt_low.csv")

    assert result.cleaning.excluded == 1
    assert excluded_source_rows(qcon) == [2]
    assert clean_source_rows(qcon) == [1, 3]


def test_the_raw_table_is_untouched(qcon, run_fixture):
    """Locked decision 1: every number stays reproducible from the file plus the ruleset."""
    run_fixture("con_high_lt_low.csv")
    assert qcon.execute("SELECT count(*) FROM stage.market_record").fetchone() == (3,)


def test_an_exact_duplicate_is_dropped_and_the_lowest_source_row_is_kept(qcon, run_fixture):
    _, result = run_fixture("unq_exact_duplicate.csv")

    assert result.cleaning.dedupe_dropped == 1
    assert result.cleaning.excluded == 0
    assert excluded_source_rows(qcon) == [3]
    assert clean_source_rows(qcon) == [1, 2, 4]


def test_a_key_conflict_excludes_every_row_in_it(qcon, run_fixture):
    _, result = run_fixture("unq_key_conflict.csv")

    assert result.cleaning.excluded == 2
    assert clean_source_rows(qcon) == [1, 4]


def test_a_warning_does_not_exclude(qcon, run_fixture):
    _, result = run_fixture("val_non_integer_volume.csv")

    assert result.cleaning.total == 0
    assert clean_source_rows(qcon) == [1, 2, 3]


def test_off_tick_price_is_flag_only_even_though_it_is_everywhere(qcon, run_fixture):
    """A systematic off-tick pattern is evidence about the tick reference, not about the price.

    Auto-excluding on it would have discarded 805 of 959 VX daily rows in this corpus for a
    settlement convention that is not an error.
    """
    qcon.execute("UPDATE dq.dq_rule SET severity = 'error' WHERE rule_id = 'VAL.OFF_TICK_PRICE'")
    _, result = run_fixture("val_off_tick_price.csv")

    assert findings(qcon, result.run_id, "VAL.OFF_TICK_PRICE")
    assert result.cleaning.total == 0


def test_an_info_finding_never_excludes(qcon, run_fixture):
    _, result = run_fixture("val_extreme_volume.csv")
    assert result.cleaning.total == 0


def test_a_session_scoped_finding_has_no_record_to_exclude(qcon, run_fixture):
    """`CMP.SESSION_MISSING` is an `error`, but the record it is about does not exist."""
    _, result = run_fixture("cmp_session_missing.csv")

    assert findings(qcon, result.run_id, "CMP.SESSION_MISSING")
    assert result.cleaning.total == 0


def test_cleaning_is_idempotent(qcon, run_fixture, fixture_path):
    """The property check: re-running the rules must not double the decision log."""
    from loupe.quality import run_rules

    batch, _ = run_fixture("unq_key_conflict.csv")
    first = clean_source_rows(qcon)
    actions = qcon.execute("SELECT count(*) FROM dq.cleaning_action").fetchone()[0]

    again = run_rules(qcon, batch_id=batch.batch_id)

    assert again.cleaning.total == 0
    assert qcon.execute("SELECT count(*) FROM dq.cleaning_action").fetchone()[0] == actions
    assert clean_source_rows(qcon) == first


def test_the_clean_view_is_derived_and_replayable(qcon, run_fixture):
    """Deleting the decision log restores the raw basis; nothing was mutated to get here."""
    run_fixture("con_high_lt_low.csv")
    assert clean_source_rows(qcon) == [1, 3]

    qcon.execute("DELETE FROM dq.cleaning_action")
    assert clean_source_rows(qcon) == [1, 2, 3]


def test_every_cleaning_action_names_the_rule_that_caused_it(qcon, run_fixture):
    run_fixture("val_non_positive_price.csv")
    rows = qcon.execute(
        "SELECT rule_id, action, rationale FROM dq.cleaning_action"
    ).fetchall()

    assert rows == [
        (
            "VAL.NON_POSITIVE_PRICE",
            "exclude",
            "default cleaning policy for error finding on VAL.NON_POSITIVE_PRICE",
        )
    ]


def test_the_exclusion_rate_is_measurable(qcon, run_fixture):
    """The shape `plans/02-quality.md` done-when 12 asks for, exercised on a fixture."""
    from loupe.quality import exclusion_rate

    run_fixture("unq_key_conflict.csv")
    report = exclusion_rate(qcon)

    assert report["records"] == 4
    assert report["excluded"] == 2
    assert report["excluded_pct"] == 50.0
    assert report["by_rule"] == [
        {"rule_id": "UNQ.KEY_CONFLICT", "action": "exclude", "records": 2}
    ]
    assert report["by_root"][0]["root"] == "ES"


def test_source_rows_survive_into_the_decision_log(qcon, run_fixture):
    """The traceability spine: a decision must be able to name row n of the source file."""
    run_fixture("con_high_lt_low.csv")
    record_ids = [
        int(row[0])
        for row in qcon.execute("SELECT record_id FROM dq.cleaning_action").fetchall()
    ]
    assert source_rows(qcon, record_ids) == [2]
