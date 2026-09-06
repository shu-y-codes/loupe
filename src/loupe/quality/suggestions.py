"""Suggestions — a proposed change, its rationale, and what it would do (spec §13).

**Report-only in v1** (locked decision 10). Each suggestion names a target, an operation and
its parameters, and says what applying it would suppress; nothing here writes to `dq.dq_rule`
or `ref.session_calendar`, and the payload carries no apply or dismiss affordance. Wiring the
actions — mutate the catalogue, re-run the scope, return before and after scores — is the
extension `specs/api-contract.md` §7.1 describes.

That last point is a decision and not an omission. §13's worked JSON ends with
`"actions": ["apply", "dismiss"]` and adds that in v1 they are not wired; this module leaves
the key out entirely rather than shipping it inert, because a list of actions in a payload is
an instruction to a client to render two buttons, and the one thing every layer of this release
has had to keep is that there are none.

**Every generator is triggered by a pattern**, so a suggestion inherits the exposure correction
that made the pattern worth reporting: it is never "this rule fired a lot". Generators are
deterministic functions of `(pattern, reference data)` — no model, no ranking heuristic that
cannot be read off the page.

**Three of §13's ten triggers are absent, and they share one cause.** "Outlier prices clustering
at exactly 10x", "same field null in a fixed source column" and the off-tick trigger's *field*
half all need to know which field each finding implicated, and that lives only in
`dq.dq_finding.details` — evidence, which `specs/data-model.md` §4 says is never grouped on and
§11.7 refuses to aggregate for the same reason. `VAL.OFF_TICK_PRICE` is still covered here
through the granularity it concentrates in, which is the half the fix actually turns on: the
vendor's daily `close` is a settlement, and that is a property of `(root, daily)` rather than of
any individual finding.

`TIM.TIMEZONE_MISALIGNED` is absent for a different reason and needs no fix: it is file-scoped
and critical, so it produces exactly one finding, and one finding is not a pattern. The finding
already carries the measured offset, and Specifics renders it as its own evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from .patterns import Pattern, find_patterns

#: How a pattern's strength becomes a suggestion's confidence. A number rather than a word
#: because §13's shape asks for one, and a floor of 0.5 because a pattern that cleared the lift
#: and support thresholds is already evidence — the scale runs from "worth reading" to "hard to
#: argue with", not from zero.
_CONFIDENCE_FLOOR = 0.5


@dataclass(frozen=True)
class Suggestion:
    """One proposed change, in the shape §13 fixes. No `actions` key — see the module note."""

    suggestion_id: str
    from_pattern: str
    kind: str
    title: str
    rationale: str
    evidence: dict[str, Any]
    proposed_change: dict[str, Any]
    expected_effect: dict[str, Any]
    confidence: float

    def as_json(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "from_pattern": self.from_pattern,
            "kind": self.kind,
            "title": self.title,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "proposed_change": self.proposed_change,
            "expected_effect": self.expected_effect,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class _Scope:
    """What the report was asked about, and the reference data a generator needs."""

    con: duckdb.DuckDBPyConnection
    contracts: list[str] | None
    start: date | None
    end: date | None
    roots: dict[str, str]
    last_sessions: dict[str, date]
    early_closes: set[tuple[str, date]]


Generator = Callable[[Pattern, _Scope], "Suggestion | None"]


def suggest(
    con: duckdb.DuckDBPyConnection,
    *,
    contracts: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    run_id: str | None = None,
    patterns: list[Pattern] | None = None,
    **pattern_options: Any,
) -> list[Suggestion]:
    """Every suggestion the patterns in scope support, strongest first.

    `patterns` is injectable so a caller that has already computed them — the API serves both
    reports from one request path — does not compute them twice and risk the two lists
    disagreeing about what was found.
    """
    found = (
        patterns
        if patterns is not None
        else find_patterns(
            con, contracts=contracts, start=start, end=end, run_id=run_id, **pattern_options
        )
    )
    if not found:
        return []

    scope = _scope(con, contracts, start, end)
    suggestions: list[Suggestion] = []
    for pattern in found:
        for generate in GENERATORS:
            suggestion = generate(pattern, scope)
            if suggestion is not None:
                suggestions.append(suggestion)
                # One suggestion per pattern: the generators are ordered most specific first,
                # and two proposals for one piece of evidence would ask the reader to choose
                # between them with nothing to choose on.
                break
    return sorted(suggestions, key=lambda s: (-s.confidence, s.suggestion_id))


def suggestion_id(pattern: Pattern, operation: str) -> str:
    """Stable, like `pattern_id`, and for the same reason: the report is recomputed per call."""
    digest = hashlib.sha1(f"{pattern.pattern_id}|{operation}".encode()).hexdigest()
    return f"s_{digest[:16]}"


# ------------------------------------------------------------------------------ generators


def _halt_window(pattern: Pattern, scope: _Scope) -> Suggestion | None:
    """Gaps concentrated in a fixed daily hour — the maintenance break, most likely.

    The strongest signal in this corpus's shape: a run of missing slots that lands in the same
    hour every session is a session the calendar has wrong, not data anyone lost.
    """
    if pattern.rule_id != "CMP.MISSING_TIMESTAMP" or pattern.dimension != "hour_of_day":
        return None
    start_local, end_local = _hours(pattern.bucket)
    root = _one_root(scope)
    return _build(
        pattern,
        scope,
        kind="calendar",
        operation="add_halt_window",
        title=f"Suppress the {start_local}-{end_local} break for {root or 'this root'}",
        rationale=(
            f"{pattern.support} missing-timestamp findings across {pattern.distinct_days} "
            f"sessions fall in the {pattern.bucket} hour, which holds only "
            f"{round(100 * pattern.share_of_records, 1)}% of the records — {pattern.lift}x the "
            "exposure. A gap that recurs at the same clock time every session is a session "
            "boundary the calendar does not know about, not data that went missing."
        ),
        target="ref.session_calendar",
        params={"root": root, "start_local": start_local, "end_local": end_local},
    )


def _holiday_or_roll(pattern: Pattern, scope: _Scope) -> Suggestion | None:
    """Whole sessions missing on one date — a closure the calendar missed, or the roll.

    Two branches because the same evidence has two explanations and they take opposite fixes.
    A session missing inside the final days of a contract's life is the roll: volume has
    migrated to the next month and nothing is wrong. A session missing on a date the calendar
    already marks an early close is a closure that was fuller than the calendar thinks.
    """
    if pattern.rule_id != "CMP.SESSION_MISSING" or pattern.dimension != "trade_date":
        return None
    day = date.fromisoformat(pattern.bucket)
    root = _one_root(scope)
    near_expiry = any(
        (last - day).days <= _ROLL_DAYS and day <= last
        for last in scope.last_sessions.values()
    )
    if near_expiry:
        return _build(
            pattern,
            scope,
            kind="rule",
            operation="set_param",
            title="Widen the roll window so the final sessions stop reporting as missing",
            rationale=(
                f"{pattern.support} absent-session findings fall on {pattern.bucket}, within "
                f"{_ROLL_DAYS} days of the last session held for this contract. Volume "
                "migrates to the deferred month before expiry, so the absence is the roll "
                "rather than a gap, and ROL.THIN_NEAR_EXPIRY's window is what suppresses it."
            ),
            target="dq.dq_rule",
            params={"rule_id": "ROL.THIN_NEAR_EXPIRY", "param": "days", "at_least": _ROLL_DAYS},
        )
    if root and (root, day) in scope.early_closes:
        return _build(
            pattern,
            scope,
            kind="calendar",
            operation="add_holiday",
            title=f"Record {pattern.bucket} as a full closure for {root}",
            rationale=(
                f"{pattern.support} absent-session findings fall on {pattern.bucket}, a date "
                "the calendar already marks an early close. No records arrived at all, which "
                "is a full closure — and a closure is not expected, so it should not be in the "
                "completeness denominator."
            ),
            target="ref.session_calendar",
            params={"root": root, "trade_date": pattern.bucket, "is_holiday": True},
        )
    return None


def _dedupe_tie_break(pattern: Pattern, scope: _Scope) -> Suggestion | None:
    """Key conflicts concentrated in one delivery — a source that needs a tie-break policy.

    A key conflict is two *different* values for one key, and §14 deliberately excludes every
    row rather than guessing a winner. When one file produces nearly all of them, the winner is
    knowable from outside the file — the vendor's own convention — and that is a policy for the
    source rather than a judgement per row.
    """
    if pattern.rule_id != "UNQ.KEY_CONFLICT" or pattern.dimension != "batch":
        return None
    return _build(
        pattern,
        scope,
        kind="rule",
        operation="set_dedupe_policy",
        title=f"Adopt a dedupe tie-break for {pattern.bucket}",
        rationale=(
            f"{round(100 * pattern.share_of_findings)}% of key-conflict findings came from "
            f"{pattern.bucket}, {pattern.lift}x its share of records. Default cleaning excludes "
            "every row of a conflict because one file gives no principled winner; a per-source "
            "policy supplies one from outside the file instead of discarding both settlements."
        ),
        target="dq.dq_rule",
        params={
            "rule_id": "UNQ.KEY_CONFLICT",
            "source": pattern.bucket,
            "tie_break": "lowest_source_row",
        },
    )


def _tick_reference(pattern: Pattern, scope: _Scope) -> Suggestion | None:
    """Off-tick prices concentrated in one granularity — the lattice is wrong, not the prices.

    The corpus's worked example (§13, `specs/sample-corpus.md` §7.3): VX daily `close` is off
    the 0.01 lattice on 805 of 959 rows and 0 of 373,886 minute rows. 84% of a contract's prices
    are not invalid; the daily close is a settlement carried to more decimals than the tick, and
    the fix is to mark the field settlement-bearing rather than to discard the column.
    """
    if pattern.rule_id != "VAL.OFF_TICK_PRICE" or pattern.dimension != "frequency":
        return None
    root = _one_root(scope)
    if pattern.bucket == "daily":
        return _build(
            pattern,
            scope,
            kind="tick",
            operation="mark_settlement_bearing",
            title=f"Exempt the daily close for {root or 'this root'} from the tick lattice",
            rationale=(
                f"{round(100 * pattern.share_of_findings)}% of off-tick findings sit in the "
                f"daily config, {pattern.lift}x its share of records, while the minute tape on "
                "the same lattice is clean. A settlement is struck by the exchange and carried "
                "to more decimals than the traded tick, so this is the tick reference being "
                "wrong for one field, not the prices being wrong."
            ),
            target="ref.tick",
            params={"root": root, "frequency": "daily", "field": "close", "exempt": True},
        )
    return _build(
        pattern,
        scope,
        kind="tick",
        operation="correct_tick_reference",
        title=f"Review the {pattern.bucket} tick for {root or 'this root'}",
        rationale=(
            f"{round(100 * pattern.share_of_findings)}% of off-tick findings sit in the "
            f"{pattern.bucket} config, {pattern.lift}x its share of records. A lattice violated "
            "by one granularity and not the other is a reference that describes the wrong "
            "granularity."
        ),
        target="ref.tick",
        params={"root": root, "frequency": pattern.bucket},
    )


def _settlement_close(pattern: Pattern, scope: _Scope) -> Suggestion | None:
    """Close-convention differences on nearly every session — stop comparing the two closes.

    `REC.CLOSE_CONVENTION` is `info` and correct on every one of those sessions (§8.4). Firing
    on almost all of them is not a defect, it is the batch telling you what its `close` column
    means, and recording that on the batch retires a report nobody needs to read twice.
    """
    # The `frequency` dimension and no other. §12 calls frequency required precisely because a
    # settlement-close pattern belongs to the granularity: the same rule also concentrates in
    # the hour around the mark, and generating from both would put the same proposed change in
    # the report twice with two different pieces of evidence behind it.
    if pattern.rule_id != "REC.CLOSE_CONVENTION" or pattern.dimension != "frequency":
        return None
    return _build(
        pattern,
        scope,
        kind="ingest",
        operation="set_close_convention",
        title="Record the vendor close as a settlement for this source",
        rationale=(
            f"{pattern.support} sessions across {pattern.distinct_days} days differ in exactly "
            "the way a settlement differs from a last trade: the vendor close sits nearer the "
            "settlement mark than the session end. Recording the convention on the batch says "
            "so once, instead of reporting the same expected difference every session."
        ),
        target="stage.ingest_batch",
        params={"close_convention": "settlement", "bucket": pattern.bucket},
    )


def _shortfall_on_roll(pattern: Pattern, scope: _Scope) -> Suggestion | None:
    """Volume shortfalls concentrated on a date — the roll, where volume trades as spreads.

    The tape carries about 95% of reported daily volume, and the low tail falls on roll dates
    where much of the volume trades as calendar spreads that never print on either outright
    leg (`specs/sample-corpus.md` §6.4). A shortfall there is the market, not the feed.
    """
    if pattern.rule_id != "REC.VOLUME_SHORTFALL" or pattern.dimension != "trade_date":
        return None
    return _build(
        pattern,
        scope,
        kind="rule",
        operation="suppress_on_dates",
        title=f"Stop checking the volume shortfall on {pattern.bucket}",
        rationale=(
            f"{round(100 * pattern.share_of_findings)}% of volume-shortfall findings fall on "
            f"{pattern.bucket}, {pattern.lift}x that date's share of records. Roll dates trade "
            "much of their volume as calendar spreads, which are reported to the exchange "
            "without printing on either outright leg, so the tape is short by construction."
        ),
        target="dq.dq_rule",
        params={
            "rule_id": "REC.VOLUME_SHORTFALL",
            "suppress_dates": [pattern.bucket],
        },
    )


#: Ordered most specific first; the first match wins (see `suggest`).
GENERATORS: tuple[Generator, ...] = (
    _halt_window,
    _holiday_or_roll,
    _dedupe_tie_break,
    _tick_reference,
    _settlement_close,
    _shortfall_on_roll,
)

#: The roll horizon a suggestion reasons about, taken from `ROL.THIN_NEAR_EXPIRY`'s seeded
#: default so the two agree about what "near expiry" means.
_ROLL_DAYS = 10


# --------------------------------------------------------------------------------- support


def _build(
    pattern: Pattern,
    scope: _Scope,
    *,
    kind: str,
    operation: str,
    title: str,
    rationale: str,
    target: str,
    params: dict[str, Any],
) -> Suggestion:
    return Suggestion(
        suggestion_id=suggestion_id(pattern, operation),
        from_pattern=pattern.pattern_id,
        kind=kind,
        title=title,
        rationale=rationale,
        evidence={
            "findings": pattern.support,
            "sessions": pattern.distinct_days,
            "lift": pattern.lift,
            "share_of_findings": pattern.share_of_findings,
            "share_of_records": pattern.share_of_records,
            "rule_id": pattern.rule_id,
            "bucket": pattern.bucket,
        },
        proposed_change={"target": target, "operation": operation, "params": params},
        expected_effect=_expected_effect(pattern, scope),
        confidence=_confidence(pattern),
    )


def _expected_effect(pattern: Pattern, scope: _Scope) -> dict[str, Any]:
    """What applying the change would do, dry-run before display (§13).

    Dried against the metrics the score was computed from rather than by re-running the rules:
    `mart.dq_metric_daily` already carries the expected and affected record counts per day, so
    the delta is arithmetic over the same denominator the dashboard shows. Re-running a scope
    inside a read endpoint would be the alternative, and it would make a report a write.

    `completeness_delta_pct` appears only for a completeness rule, because it is the one
    dimension whose denominator counts records that are not there; for the others the honest
    statement is how many findings and rows the change retires.
    """
    con = scope.con
    row = con.execute(
        """
        SELECT coalesce(sum(f.affected_rows), 0), any_value(r.dimension),
               any_value(r.severity)
        FROM dq.dq_finding f JOIN dq.dq_rule r USING (rule_id)
        WHERE f.rule_id = ? AND f.status = 'open'
        """,
        [pattern.rule_id],
    ).fetchone()
    rows_all = int(row[0] or 0)
    dimension, severity = row[1], row[2]
    # The pattern's own share of the rule, applied to the rows the rule accounts for: the
    # change retires the bucket, not the rule.
    rows_in_bucket = round(rows_all * pattern.share_of_findings)

    effect: dict[str, Any] = {
        "findings_suppressed": pattern.support,
        "records_recovered": rows_in_bucket,
        "basis": "dry run over mart.dq_metric_daily; no rules were re-run",
    }
    if severity == "info":
        # Said out loud, because "24 findings suppressed" otherwise reads as a score
        # improvement. An `info` rule is in no numerator (§11.1), so applying this change
        # quietens a report and moves no number — which is still a good reason to apply it.
        effect["score_impact"] = (
            "none — this rule is info and enters no score numerator, so the change retires a "
            "report rather than raising a score"
        )
        return effect
    if dimension == "completeness":
        expected = con.execute(
            """
            SELECT coalesce(sum(expected_records), 0)
            FROM mart.dq_metric_daily
            WHERE dimension = 'completeness' AND frequency <> 'cross'
            """
        ).fetchone()
        denominator = int(expected[0] or 0)
        effect["completeness_delta_pct"] = (
            round(100.0 * rows_in_bucket / denominator, 2) if denominator else None
        )
    return effect


def _confidence(pattern: Pattern) -> float:
    """Deterministic, and bounded so it never reads as a probability of being right."""
    strength = min(1.0, pattern.lift / 20.0)
    weight = min(1.0, pattern.support / 200.0)
    return round(_CONFIDENCE_FLOOR + (1 - _CONFIDENCE_FLOOR) * (strength + weight) / 2, 2)


def _hours(bucket: str) -> tuple[str, str]:
    """`"16:00-17:00 America/Chicago"` back into its two local times."""
    span = bucket.split(" ", 1)[0]
    start, _, end = span.partition("-")
    return f"{start}:00", f"{end}:00"


def _one_root(scope: _Scope) -> str | None:
    """The root, when the scope names exactly one. `None` rather than a guess otherwise.

    A proposed calendar or tick change is per root, so a scope spanning two roots cannot name
    one — and naming the first would put a change against the wrong product in the payload.
    """
    roots = set(scope.roots.values())
    return next(iter(roots)) if len(roots) == 1 else None


def _scope(
    con: duckdb.DuckDBPyConnection,
    contracts: list[str] | None,
    start: date | None,
    end: date | None,
) -> _Scope:
    clause, args = ("TRUE", [])
    if contracts:
        placeholders = ", ".join("?" for _ in contracts)
        clause, args = (f"r.contract_id IN ({placeholders})", list(contracts))
    rows = con.execute(
        f"""
        SELECT r.contract_id, any_value(c.root), max(r.trade_date)
        FROM stage.market_record r
        LEFT JOIN ref.contract c ON c.contract_id = r.contract_id
        WHERE {clause}
        GROUP BY 1
        """,
        args,
    ).fetchall()
    roots = {row[0]: row[1] for row in rows if row[1]}
    last_sessions = {row[0]: row[2] for row in rows if row[2]}
    early = con.execute(
        "SELECT root, trade_date FROM ref.session_calendar WHERE is_early_close"
    ).fetchall()
    return _Scope(
        con=con,
        contracts=contracts,
        start=start,
        end=end,
        roots=roots,
        last_sessions=last_sessions,
        early_closes={(row[0], row[1]) for row in early},
    )
