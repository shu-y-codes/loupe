"""The publish gate: which findings touch a session, and what that withholds."""

from __future__ import annotations

from datetime import date

from loupe.data import load_file
from loupe.insights import (
    COUNTED_SCOPES,
    blocked_sessions,
    published_bars,
    published_vwap,
    read_bars,
    session_quality,
)
from loupe.quality import run_rules


def _assess(icon, fixture_path, name, **kwargs):
    batch = load_file(icon, fixture_path(name))
    return batch, run_rules(icon, batch_id=batch.batch_id, **kwargs)


def test_finding_count_is_exactly_the_record_and_session_findings(icon, fixture_path):
    """Count narrow, escalate wide.

    `CMP.SPARSE_SERIES` is one statement about the whole contract. Counting it on every bar
    would shift the trend by a constant and say nothing about which session is worse — but it
    still reaches `max_severity`, because a bar inside a broken series is not trustworthy
    just because the breakage was described once.
    """
    _assess(icon, fixture_path, "cmp_sparse_series.csv")

    by_scope = dict(
        icon.execute(
            """
            SELECT r.scope, count(*)
            FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
            WHERE f.status = 'open' GROUP BY 1
            """
        ).fetchall()
    )
    assert by_scope.get("series", 0) > 0, "fixture no longer produces a series-scope finding"

    for key, quality in session_quality(icon).items():
        contract_id, frequency, trade_date = key
        expected = icon.execute(
            f"""
            SELECT count(*)
            FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
            WHERE f.status = 'open' AND r.scope IN {COUNTED_SCOPES}
              AND f.contract_id = ? AND f.frequency = ? AND f.trade_date = ?
            """,
            [contract_id, frequency, trade_date],
        ).fetchone()[0]
        assert quality.finding_count == expected


def test_a_series_finding_raises_severity_without_being_counted(icon, fixture_path):
    """The two columns answer different questions, so they must be able to disagree."""
    _assess(icon, fixture_path, "rol_no_successor.csv")
    icon.execute("DELETE FROM dq.dq_finding WHERE rule_id <> 'ROL.NO_SUCCESSOR'")
    resolved = session_quality(icon, frequency="daily")

    assert resolved
    assert all(q.finding_count == 0 for q in resolved.values())
    assert any(q.max_severity == "info" for q in resolved.values())


def test_a_finding_on_one_frequency_does_not_touch_the_other(icon, fixture_path):
    """Slice 2 measured that all 43 excluded records are vendor daily rows.

    Without the frequency predicate, those record-scope errors would attach to minute bars
    that share nothing with them but a date.
    """
    _assess(icon, fixture_path, "insights_vwap_window.csv")
    _assess(icon, fixture_path, "con_derived_bar_invalid_vendor.csv")
    icon.execute(
        """
        INSERT INTO dq.dq_finding
          (run_id, rule_id, contract_id, frequency, trade_date, severity, status)
        SELECT run_id, 'CON.CLOSE_OUT_OF_RANGE', 'ESZ25', 'daily', DATE '2025-09-15',
               'error', 'open'
        FROM dq.dq_run LIMIT 1
        """
    )
    minute = session_quality(icon, contract_id="ESZ25", frequency="minute")
    daily_key = ("ESZ25", "minute", date(2025, 9, 15))

    assert minute[daily_key].max_severity != "error"


def test_a_critical_finding_blocks_its_slice(icon, fixture_path, load_and_build):
    """`TIM.TIMEZONE_MISALIGNED` is the rule slice 2 wrote findings against for this.

    It is `file`-scope and the only non-record `critical` in the catalogue, so a gate that
    ignored file scope could never fire on the one rule built to trigger it.
    """
    load_and_build("tim_timezone_misaligned.csv")
    run_rules(icon)

    blocked = blocked_sessions(icon, frequency="minute")
    assert blocked
    assert all("TIM.TIMEZONE_MISALIGNED" in q.blocking_rule_ids for q in blocked)


def test_blocked_is_distinguishable_from_empty(icon, fixture_path, load_and_build):
    """An empty list would say "no data" about a series that exists and is withheld."""
    load_and_build("tim_timezone_misaligned.csv")
    run_rules(icon)

    assert read_bars(icon), "the bars exist; the gate is what withholds them"
    series = published_bars(icon)

    assert series.rows == ()
    assert series.blocked
    assert not series.unavailable
    assert series.blocking_rule_ids == ("TIM.TIMEZONE_MISALIGNED",)


def test_a_clean_slice_publishes(load_and_build, icon):
    load_and_build("insights_vwap_window.csv")
    run_rules(icon)
    series = published_bars(icon)

    assert not series.blocked
    assert len(series.rows) == 1


def test_the_gate_withholds_the_vwap_line_too(icon, load_and_build):
    """A misread timezone moves every session boundary, so the line is wrong end to end."""
    load_and_build("tim_timezone_misaligned.csv")
    run_rules(icon)
    series = published_vwap(icon)

    assert series.blocked
    assert series.rows == ()


def test_a_dispositioned_finding_stops_blocking(icon, load_and_build):
    """An accepted finding has been looked at and judged; it is no longer a live objection."""
    load_and_build("tim_timezone_misaligned.csv")
    run_rules(icon)
    assert published_bars(icon).blocked

    icon.execute("UPDATE dq.dq_finding SET status = 'accepted' WHERE severity = 'critical'")
    assert not published_bars(icon).blocked
