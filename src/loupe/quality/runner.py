"""A rule pass: open a run, dispatch every enabled runner, write findings, close the run.

Everything a run needs that is not a rule — the scoped record set, the coverage windows, the
roll windows — is computed **once** and shared. A rule that recomputed its own window would
be free to disagree with the rule next to it about which sessions were expected.

The scope filter and the ruleset hash are both recorded on `dq.dq_run`, because a score that
moved between two runs must be attributable to the data or to the ruleset and not ambiguously
to both (spec §17 step 6).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

import duckdb

from . import rules as _rules  # noqa: F401  (import registers every runner)
from .catalogue import CATALOGUE, DEFAULT_MIN_RECORDS
from .cleaning import CleaningReport, apply_default_cleaning
from .errors import RulesNotSeeded
from .registry import (
    RECORDS,
    REGISTRY,
    WINDOWS,
    Finding,
    RuleContext,
    RuleRefusal,
    RuleRow,
    RunScope,
)
from .scoring import SliceScore, persist_daily_metrics, score_slice
from .seed import ruleset_hash
from .windows import RunInputs, resolve_roll_windows, resolve_windows

#: The rule whose params define the completeness bounds. The liquidity floor is that rule's
#: parameter, and the window it produces is shared, so one row is the single place a
#: deployment changes what "expected to be present" means.
WINDOW_RULE = "CMP.SESSION_MISSING"
#: The rule whose params define the roll window that completeness suppresses inside.
ROLL_RULE = "ROL.THIN_NEAR_EXPIRY"


@dataclass(frozen=True)
class RunResult:
    """What a rule pass did, returned rather than logged so tests can assert on it."""

    run_id: str
    ruleset_hash: str
    status: str
    records_in_scope: int
    findings_count: int
    findings_by_rule: dict[str, int] = field(default_factory=dict)
    refusals: dict[str, str] = field(default_factory=dict)
    rules_evaluated: tuple[str, ...] = ()
    cleaning: CleaningReport | None = None


# ------------------------------------------------------------------------ scope setup


def _rule_rows(con: duckdb.DuckDBPyConnection) -> dict[str, RuleRow]:
    rows = con.execute(
        """
        SELECT rule_id, dimension, name, severity, scope, applies_to_frequency,
               CAST(params AS VARCHAR), enabled, triage_weight
        FROM dq.dq_rule
        """
    ).fetchall()
    if not rows:
        raise RulesNotSeeded
    return {
        row[0]: RuleRow(
            rule_id=row[0],
            dimension=row[1],
            name=row[2],
            severity=row[3],
            scope=row[4],
            applies_to_frequency=row[5],
            params=json.loads(row[6]) if row[6] else {},
            enabled=bool(row[7]),
            triage_weight=float(row[8]),
        )
        for row in rows
    }


def _materialise_records(con: duckdb.DuckDBPyConnection, scope: RunScope) -> int:
    """Project the scoped records once, with the reference and batch context joined on.

    A temp table rather than a view: every rule reads it, several read it more than once, and
    the scope filter should be paid for once per run rather than once per rule.
    """
    clauses = ["TRUE"]
    args: list[object] = []
    if scope.batch_id is not None:
        clauses.append("r.batch_id = ?")
        args.append(scope.batch_id)
    if scope.contract_ids:
        placeholders = ", ".join("?" for _ in scope.contract_ids)
        clauses.append(f"r.contract_id IN ({placeholders})")
        args.extend(scope.contract_ids)
    if scope.frequencies:
        placeholders = ", ".join("?" for _ in scope.frequencies)
        clauses.append(f"r.frequency IN ({placeholders})")
        args.extend(scope.frequencies)

    con.execute(f"DROP TABLE IF EXISTS {RECORDS}")
    con.execute(
        f"""
        CREATE TEMP TABLE {RECORDS} AS
        SELECT r.record_id, r.batch_id, r.source_row, r.contract_id, r.frequency,
               r.ts_exchange, r.ts_utc, r.trade_date,
               r.open, r.high, r.low, r.close, r.volume, r.volume_source, r.open_interest,
               r.ingested_at,
               c.root, c.exchange, c.first_trade_date, c.last_trade_date,
               b.bar_interval, b.inferred_interval, b.source_timezone
        FROM stage.market_record r
        LEFT JOIN ref.contract c ON c.contract_id = r.contract_id
        LEFT JOIN stage.ingest_batch b ON b.batch_id = r.batch_id
        WHERE {" AND ".join(clauses)}
        """,
        args,
    )
    row = con.execute(f"SELECT count(*) FROM {RECORDS}").fetchone()
    return int(row[0]) if row else 0


def _materialise_windows(con: duckdb.DuckDBPyConnection, inputs: RunInputs) -> None:
    """Publish the coverage and roll windows as a table the rule SQL can join to."""
    con.execute(f"DROP TABLE IF EXISTS {WINDOWS}")
    con.execute(
        f"""
        CREATE TEMP TABLE {WINDOWS} (
          contract_id VARCHAR, frequency VARCHAR, start_date DATE, end_date DATE,
          basis VARCHAR, roll_start DATE, roll_end DATE
        )
        """
    )
    rows = []
    for key, window in inputs.windows.items():
        roll = inputs.roll_windows.get(key)
        rows.append(
            (
                window.contract_id,
                window.frequency,
                window.start,
                window.end,
                window.basis,
                roll.start if roll else None,
                roll.end if roll else None,
            )
        )
    if rows:
        con.executemany(f"INSERT INTO {WINDOWS} VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


@contextmanager
def scoped(
    con: duckdb.DuckDBPyConnection, scope: RunScope
) -> Iterator[tuple[RunInputs, dict[str, RuleRow], int]]:
    """Materialise the record set and the shared windows for the duration of a block.

    Scoring uses this too, so a score is computed over exactly the record set and the windows
    the rules were evaluated against.
    """
    rows = _rule_rows(con)
    records = _materialise_records(con, scope)

    window_params = rows[WINDOW_RULE].params if WINDOW_RULE in rows else {}
    roll_params = rows[ROLL_RULE].params if ROLL_RULE in rows else {}
    inputs = RunInputs(
        windows=resolve_windows(con, volume_floor=float(window_params.get("volume_floor", 0))),
        roll_windows=resolve_roll_windows(
            con,
            days=int(roll_params.get("days", 0)),
            collapse_ratio=float(roll_params.get("collapse_ratio", 0.0)),
        ),
    )
    _materialise_windows(con, inputs)
    try:
        yield inputs, rows, records
    finally:
        con.execute(f"DROP TABLE IF EXISTS {RECORDS}")
        con.execute(f"DROP TABLE IF EXISTS {WINDOWS}")


# ----------------------------------------------------------------------------- the pass


def _write_findings(
    con: duckdb.DuckDBPyConnection, run_id: str, findings: list[Finding]
) -> None:
    if not findings:
        return
    con.executemany(
        """
        INSERT INTO dq.dq_finding
          (run_id, rule_id, contract_id, frequency, compare_frequency, trade_date,
           ts_start_utc, ts_end_utc, record_id, affected_rows, severity, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                f.rule_id,
                f.contract_id,
                f.frequency,
                f.compare_frequency,
                f.trade_date,
                f.ts_start_utc,
                f.ts_end_utc,
                f.record_id,
                f.affected_rows,
                f.severity,
                json.dumps(dict(f.details), default=str, sort_keys=True),
            )
            for f in findings
        ],
    )


def _execute_pass(
    con: duckdb.DuckDBPyConnection,
    scope: RunScope,
    inputs: RunInputs,
    rows: dict[str, RuleRow],
    records: int,
    rule_ids: tuple[str, ...] | None,
    digest: str,
) -> RunResult:
    """Open the run, dispatch the runners, write the findings, close the run."""
    run_id = str(
        con.execute(
            """
            INSERT INTO dq.dq_run (batch_id, ruleset_hash, scope_filter, status)
            VALUES (?, ?, ?, 'running')
            RETURNING run_id
            """,
            [scope.batch_id, digest, json.dumps(scope.as_json())],
        ).fetchone()[0]
    )

    findings: list[Finding] = []
    by_rule: dict[str, int] = {}
    refusals: dict[str, str] = {}
    evaluated: list[str] = []

    try:
        # Catalogue order rather than registry order, so a run is reproducible and a diff of
        # two runs' findings reads in a stable sequence.
        for spec in CATALOGUE:
            runner = REGISTRY.get(spec.rule_id)
            row = rows.get(spec.rule_id)
            if runner is None or row is None or not row.enabled:
                continue
            if rule_ids is not None and spec.rule_id not in rule_ids:
                continue
            ctx = RuleContext(con=con, rule=row, scope=scope, inputs=inputs)
            try:
                produced = runner(ctx)
            except RuleRefusal as refusal:
                refusals[spec.rule_id] = str(refusal)
                continue
            evaluated.append(spec.rule_id)
            if produced:
                by_rule[spec.rule_id] = len(produced)
                findings.extend(produced)

        _write_findings(con, run_id, findings)
    except Exception:
        con.execute(
            "UPDATE dq.dq_run SET status = 'failed', finished_at = now() WHERE run_id = ?",
            [run_id],
        )
        raise

    con.execute(
        """
        UPDATE dq.dq_run
           SET status = 'succeeded', findings_count = ?, finished_at = now()
         WHERE run_id = ?
        """,
        [len(findings), run_id],
    )

    return RunResult(
        run_id=run_id,
        ruleset_hash=digest,
        status="succeeded",
        records_in_scope=records,
        findings_count=len(findings),
        findings_by_rule=by_rule,
        refusals=refusals,
        rules_evaluated=tuple(evaluated),
    )


def run_rules(
    con: duckdb.DuckDBPyConnection,
    *,
    batch_id: str | None = None,
    contract_ids: tuple[str, ...] | None = None,
    frequencies: tuple[str, ...] | None = None,
    rule_ids: tuple[str, ...] | None = None,
    clean: bool = True,
) -> RunResult:
    """Evaluate the enabled catalogue over a scope and record what it found.

    `rule_ids` narrows the pass to named rules; the ruleset hash still describes the whole
    seeded ruleset, because that is what these findings would have to be reproduced against.

    A runner that raises `RuleRefusal` is recorded as a refusal, not as a rule that found
    nothing. The run still succeeds: refusing to evaluate a completeness rule without a
    calendar is the correct outcome, not a failure.
    """
    scope = RunScope(batch_id=batch_id, contract_ids=contract_ids, frequencies=frequencies)
    digest = ruleset_hash(con)
    with scoped(con, scope) as (inputs, rows, records):
        result = _execute_pass(con, scope, inputs, rows, records, rule_ids, digest)
    cleaning = apply_default_cleaning(con, result.run_id) if clean else None
    return replace(result, cleaning=cleaning)


def assess(
    con: duckdb.DuckDBPyConnection,
    *,
    batch_id: str | None = None,
    contract_ids: tuple[str, ...] | None = None,
    frequencies: tuple[str, ...] | None = None,
    rule_ids: tuple[str, ...] | None = None,
    clean: bool = True,
    min_records: int = DEFAULT_MIN_RECORDS,
) -> tuple[RunResult, list[SliceScore]]:
    """Run the rules and score what they found, over one scope.

    Rules and scoring share the scope rather than each building their own, so the denominator
    a score reports is the same record set the findings were drawn from. This is the entry
    point the API and the UI should call; `run_rules` exists for tests that want the findings
    without the arithmetic.
    """
    scope = RunScope(batch_id=batch_id, contract_ids=contract_ids, frequencies=frequencies)
    digest = ruleset_hash(con)
    with scoped(con, scope) as (inputs, rows, records):
        result = _execute_pass(con, scope, inputs, rows, records, rule_ids, digest)
        persist_daily_metrics(con, result.run_id)
        slices = con.execute(
            f"SELECT DISTINCT contract_id, frequency FROM {RECORDS} ORDER BY 1, 2"
        ).fetchall()
        scores = [
            score_slice(con, result.run_id, contract_id, frequency, min_records=min_records)
            for contract_id, frequency in slices
        ]
    cleaning = apply_default_cleaning(con, result.run_id) if clean else None
    return replace(result, cleaning=cleaning), scores
