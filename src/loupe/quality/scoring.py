"""The DQ score: per-dimension 0-100, and a weighted mean over the dimensions in scope.

Three properties of the definition do the real work (spec §11).

**A record is counted at most once per dimension**, not once per finding. Two validity rules
firing on the same row is one invalid record, and counting it twice would let the score fall
below what any denominator justifies.

**The conditional dimension is renormalised, not defaulted.** Reconciliation exists only when
both frequencies were uploaded for a contract. Scoring a contract down — or up — because the
user uploaded one file rather than two is indefensible, so the weighted mean divides by the
weights actually in scope and the score object states which those were.

**Triage weight is not an input.** `dq.dq_rule.triage_weight` orders the fix-first worklist
and answers a different question from the score; a per-rule multiplier in §11.1 would
double-count a record two rules both fired on. Nothing in this module reads it, and
`tests/quality/test_scoring.py` asserts that changing it cannot move any score.

Completeness needs one sentence of its own. §11.1 writes it as `actual / expected`, and §11.1
also says every dimension counts its defective records. Both hold here: `actual_records` for
completeness means records that are present **and complete**, so `CMP.NULL_FIELD` lowers the
score of the dimension it belongs to, while missing slots lower it by being absent from the
numerator. `mart.dq_metric_daily` carries `actual_records` and `affected_records` side by side
so the two effects stay separable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb

from .catalogue import DEFAULT_MIN_RECORDS
from .registry import RECORDS, WINDOWS

#: Only these count as defects (spec §11.1). `info` never enters a numerator, which is what
#: keeps `OUT.*` and `REC.CLOSE_CONVENTION` reportable without being punitive.
DEFECT_SEVERITIES = ("warning", "error", "critical")

ALWAYS_IN_SCOPE = ("completeness", "uniqueness", "validity", "consistency", "timeliness")

DIMENSION_CODES = {
    "completeness": "cmp",
    "uniqueness": "unq",
    "validity": "val",
    "consistency": "con",
    "timeliness": "tim",
    "reconciliation": "rec",
}


@dataclass(frozen=True)
class DimensionScore:
    """One dimension's 0-100 sub-score, with the evidence it was computed from."""

    dimension: str
    score: float
    weight: float
    denominator: int
    basis: str
    affected_records: int
    finding_count: int

    def as_json(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "weight": self.weight,
            "denominator": self.denominator,
            "basis": self.basis,
            "affected_records": self.affected_records,
            "finding_count": self.finding_count,
        }


@dataclass(frozen=True)
class SliceScore:
    """The score object for one contract x frequency slice (spec §11.3)."""

    contract_id: str
    frequency: str
    overall: float | None
    records: int
    expected_records: int
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    dimensions_not_in_scope: list[dict[str, str]] = field(default_factory=list)
    weight_denominator: float = 0.0
    insufficient_data: bool = False
    min_records: int = DEFAULT_MIN_RECORDS

    @property
    def dimensions_in_scope(self) -> list[str]:
        return list(self.dimensions)

    @property
    def scope_signature(self) -> str:
        return "+".join(DIMENSION_CODES[d] for d in self.dimensions)

    def as_json(self) -> dict[str, Any]:
        """The semantic contract of §11.3. HTTP envelopes are the API spec's business."""
        return {
            "contract_id": self.contract_id,
            "frequency": self.frequency,
            "overall": self.overall,
            "insufficient_data": self.insufficient_data,
            "records": self.records,
            "dimensions_in_scope": self.dimensions_in_scope,
            "dimensions_not_in_scope": self.dimensions_not_in_scope,
            "scope_signature": self.scope_signature,
            "weight_denominator": self.weight_denominator,
            "dimensions": {d: s.as_json() for d, s in self.dimensions.items()},
        }


@dataclass(frozen=True)
class WorklistEntry:
    """One row of the fix-first worklist (spec §11.4).

    `rank` is `triage_weight x affected_records`, and both factors are carried alongside it so
    a reader can see whether a row is high because the defect is bad or because it is
    everywhere. It is not a severity, a probability or a currency amount.
    """

    rule_id: str
    dimension: str
    severity: str
    affected_records: int
    triage_weight: float
    rank: float
    score_if_resolved: dict[str, Any]


# ------------------------------------------------------------------------- ingredients


def _weights(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """The only weights in the score, read from `dq.score_weight` at scoring time."""
    return {
        dimension: float(weight)
        for dimension, weight in con.execute(
            "SELECT dimension, weight FROM dq.score_weight WHERE enabled"
        ).fetchall()
    }


def _actual_records(con: duckdb.DuckDBPyConnection, contract_id: str, frequency: str) -> int:
    row = con.execute(
        f"SELECT count(*) FROM {RECORDS} WHERE contract_id = ? AND frequency = ?",
        [contract_id, frequency],
    ).fetchone()
    return int(row[0]) if row else 0


def expected_records(
    con: duckdb.DuckDBPyConnection, contract_id: str, frequency: str
) -> int:
    """The completeness denominator: expected slots (minute) or sessions (daily).

    After suppressions — holidays, the roll window and everything outside the coverage window
    are not expected, so they are not in the denominator. An early close contributes nothing
    at minute granularity because its truncated grid is unknown, and a null denominator
    component is more honest than a full-session one.
    """
    row = con.execute(
        f"""
        SELECT coalesce(sum(CASE WHEN w.frequency = 'minute'
                                 THEN c.expected_slots_1m ELSE 1 END), 0)
        FROM {WINDOWS} w
        JOIN (SELECT DISTINCT contract_id, frequency, root FROM {RECORDS}
              WHERE root IS NOT NULL) s
          ON s.contract_id = w.contract_id AND s.frequency = w.frequency
        JOIN ref.session_calendar c
          ON c.root = s.root AND c.trade_date BETWEEN w.start_date AND w.end_date
        WHERE w.contract_id = ? AND w.frequency = ?
          AND NOT c.is_holiday
          AND (w.roll_start IS NULL OR c.trade_date NOT BETWEEN w.roll_start AND w.roll_end)
          AND (w.frequency <> 'minute' OR c.expected_slots_1m IS NOT NULL)
        """,
        [contract_id, frequency],
    ).fetchone()
    return int(row[0]) if row else 0


def _defects(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    frequency: str,
    *,
    exclude_rule: str | None = None,
) -> dict[str, int]:
    """Distinct defective records per dimension — at most once per dimension, per §11.1."""
    severities = ", ".join("?" for _ in DEFECT_SEVERITIES)
    rows = con.execute(
        f"""
        SELECT r.dimension, count(DISTINCT f.record_id)
        FROM dq.dq_finding f
        JOIN dq.dq_rule r USING (rule_id)
        WHERE f.run_id = ? AND f.contract_id = ? AND f.frequency = ?
          AND f.record_id IS NOT NULL
          AND f.severity IN ({severities})
          AND (? IS NULL OR f.rule_id <> ?)
        GROUP BY 1
        """,
        [run_id, contract_id, frequency, *DEFECT_SEVERITIES, exclude_rule, exclude_rule],
    ).fetchall()
    return {dimension: int(count) for dimension, count in rows}


def _finding_counts(
    con: duckdb.DuckDBPyConnection, run_id: str, contract_id: str, frequency: str
) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT r.dimension, count(*)
        FROM dq.dq_finding f
        JOIN dq.dq_rule r USING (rule_id)
        WHERE f.run_id = ? AND f.contract_id = ? AND f.frequency = ?
        GROUP BY 1
        """,
        [run_id, contract_id, frequency],
    ).fetchall()
    return {dimension: int(count) for dimension, count in rows}


def _recovered_slots(
    con: duckdb.DuckDBPyConnection, run_id: str, contract_id: str, frequency: str, rule_id: str
) -> int:
    """Slots that would come back if one session-grained completeness rule were resolved.

    A missing-slot finding has no `record_id`, so zeroing its defect count means adding the
    slots to the numerator rather than removing records from it.
    """
    severities = ", ".join("?" for _ in DEFECT_SEVERITIES)
    row = con.execute(
        f"""
        SELECT coalesce(sum(f.affected_rows), 0)
        FROM dq.dq_finding f
        JOIN dq.dq_rule r USING (rule_id)
        WHERE f.run_id = ? AND f.contract_id = ? AND f.frequency = ?
          AND f.rule_id = ? AND f.record_id IS NULL
          AND r.dimension = 'completeness'
          AND f.severity IN ({severities})
        """,
        [run_id, contract_id, frequency, rule_id, *DEFECT_SEVERITIES],
    ).fetchone()
    return int(row[0]) if row else 0


# ------------------------------------------------------------------------------ scoring


def _compose(
    *,
    contract_id: str,
    frequency: str,
    actual: int,
    expected: int,
    defects: dict[str, int],
    findings: dict[str, int],
    weights: dict[str, float],
    not_in_scope: list[dict[str, str]],
    recovered: int = 0,
    min_records: int,
) -> SliceScore:
    """Assemble the per-dimension sub-scores and the renormalised weighted mean."""
    dimensions: dict[str, DimensionScore] = {}
    out_of_scope = list(not_in_scope)

    for dimension in ALWAYS_IN_SCOPE:
        affected = defects.get(dimension, 0)
        if dimension == "completeness":
            if expected <= 0:
                out_of_scope.append(
                    {
                        "dimension": dimension,
                        "reason": "no expected records for this slice, so completeness is "
                        "undefined rather than perfect",
                    }
                )
                continue
            complete = max(0, actual + recovered - affected)
            ratio = min(1.0, complete / expected)
            denominator, basis = expected, "expected_records"
        else:
            if actual <= 0:
                out_of_scope.append(
                    {"dimension": dimension, "reason": "no records in this slice"}
                )
                continue
            ratio = max(0.0, 1.0 - affected / actual)
            denominator, basis = actual, "actual_records"

        dimensions[dimension] = DimensionScore(
            dimension=dimension,
            score=round(100.0 * ratio, 4),
            weight=weights.get(dimension, 0.0),
            denominator=denominator,
            basis=basis,
            affected_records=affected,
            finding_count=findings.get(dimension, 0),
        )

    weight_total = sum(d.weight for d in dimensions.values())
    insufficient = actual < min_records
    if insufficient or not dimensions or weight_total <= 0:
        overall = None
    else:
        overall = round(
            sum(d.weight * d.score for d in dimensions.values()) / weight_total, 4
        )

    return SliceScore(
        contract_id=contract_id,
        frequency=frequency,
        overall=overall,
        records=actual,
        expected_records=expected,
        dimensions=dimensions,
        dimensions_not_in_scope=out_of_scope,
        weight_denominator=round(weight_total, 6),
        insufficient_data=insufficient,
        min_records=min_records,
    )


def _reconciliation_note(
    con: duckdb.DuckDBPyConnection, contract_id: str
) -> dict[str, str]:
    """Why reconciliation is out of scope. Never "score 100" and never "score 0" (§11.3).

    Both reasons are statements about **the data**, not about the roadmap. They are rendered
    verbatim — `dimensions_not_in_scope` reaches the API envelope and the UI prints it under
    the score (`specs/loupe-ui-design.md`) — so a build-sequence note here would be shown to a
    reader as if it were a fact about their contract.

    The second branch is where reconciliation becomes *scoreable*: §8.6's sub-score over
    reconcilable sessions, renormalised to a 1.20 denominator by §11.3. Until `REC.*` findings
    exist there is no evidence to score, and the honest answer is this note rather than a
    numerator of zero defects — which would read as a perfect 100 and is the failure §11.3
    rejects by name.
    """
    row = con.execute(
        f"SELECT count(DISTINCT frequency) FROM {RECORDS} WHERE contract_id = ?",
        [contract_id],
    ).fetchone()
    both = bool(row and int(row[0]) > 1)
    return {
        "dimension": "reconciliation",
        "reason": (
            "no reconciliation evidence has been computed for this contract"
            if both
            else "only one frequency uploaded for this contract"
        ),
    }


def score_slice(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    frequency: str,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
) -> SliceScore:
    """Score one contract x frequency slice. Call inside `runner.scoped`."""
    return _compose(
        contract_id=contract_id,
        frequency=frequency,
        actual=_actual_records(con, contract_id, frequency),
        expected=expected_records(con, contract_id, frequency),
        defects=_defects(con, run_id, contract_id, frequency),
        findings=_finding_counts(con, run_id, contract_id, frequency),
        weights=_weights(con),
        not_in_scope=[_reconciliation_note(con, contract_id)],
        min_records=min_records,
    )


def score_if_resolved(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    frequency: str,
    rule_id: str,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
) -> SliceScore:
    """§11.1 recomputed with one rule's defect count set to zero.

    The same dry-run mechanism as `expected_effect` on a suggestion (§13). This is the number
    to lead a worklist with: it is derived from the data rather than from a dial someone set,
    and it is denominated in the units the dashboard already shows.

    Each dry-run answers "what if *this* rule were resolved", so the answers do not add up and
    are not meant to. Two rules often describe one absence — a run of missing slots is both
    `CMP.MISSING_TIMESTAMP` and the `CMP.PARTIAL_SESSION` it causes — and resolving either
    implies the same slots exist, so both show the same recovered score.
    """
    return _compose(
        contract_id=contract_id,
        frequency=frequency,
        actual=_actual_records(con, contract_id, frequency),
        expected=expected_records(con, contract_id, frequency),
        defects=_defects(con, run_id, contract_id, frequency, exclude_rule=rule_id),
        findings=_finding_counts(con, run_id, contract_id, frequency),
        weights=_weights(con),
        not_in_scope=[_reconciliation_note(con, contract_id)],
        recovered=_recovered_slots(con, run_id, contract_id, frequency, rule_id),
        min_records=min_records,
    )


def worklist(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    frequency: str,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
) -> list[WorklistEntry]:
    """The fix-first list: every rule with open findings, ranked, with its score dry-run."""
    current = score_slice(con, run_id, contract_id, frequency, min_records=min_records)
    rows = con.execute(
        """
        SELECT f.rule_id, r.dimension, r.triage_weight,
               max(f.severity) AS severity,
               count(DISTINCT coalesce(CAST(f.record_id AS VARCHAR),
                                       'range:' || CAST(f.finding_id AS VARCHAR))) AS records,
               sum(CASE WHEN f.record_id IS NULL THEN f.affected_rows ELSE 0 END) AS ranges
        FROM dq.dq_finding f
        JOIN dq.dq_rule r USING (rule_id)
        WHERE f.run_id = ? AND f.contract_id = ? AND f.frequency = ? AND f.status = 'open'
        GROUP BY 1, 2, 3
        """,
        [run_id, contract_id, frequency],
    ).fetchall()

    entries: list[WorklistEntry] = []
    for rule_id, dimension, triage_weight, severity, records, ranges in rows:
        affected = int(records) if int(ranges) == 0 else int(ranges)
        resolved = score_if_resolved(
            con, run_id, contract_id, frequency, rule_id, min_records=min_records
        )
        entries.append(
            WorklistEntry(
                rule_id=rule_id,
                dimension=dimension,
                severity=severity,
                affected_records=affected,
                triage_weight=float(triage_weight),
                rank=round(float(triage_weight) * affected, 6),
                score_if_resolved={
                    dimension: resolved.dimensions[dimension].score
                    if dimension in resolved.dimensions
                    else None,
                    "overall": resolved.overall,
                    "from": {
                        dimension: current.dimensions[dimension].score
                        if dimension in current.dimensions
                        else None,
                        "overall": current.overall,
                    },
                },
            )
        )
    return sorted(entries, key=lambda e: (-e.rank, e.rule_id))


# ----------------------------------------------------------------------------- the mart


def persist_daily_metrics(con: duckdb.DuckDBPyConnection, run_id: str) -> int:
    """Write one `mart.dq_metric_daily` row per contract x date x frequency x dimension.

    Per-day rather than per-slice because the dashboard reads a time series, and the
    per-dimension rows are the answer the user is actually looking for — the composite is
    navigation (§11.5).
    """
    severities = ", ".join("?" for _ in DEFECT_SEVERITIES)
    dimensions = ", ".join("?" for _ in ALWAYS_IN_SCOPE)
    rows = con.execute(
        f"""
        WITH dims(dimension) AS (SELECT unnest([{dimensions}])),
        actual AS (
          SELECT contract_id, frequency, trade_date, count(*) AS actual_records
          FROM {RECORDS}
          GROUP BY 1, 2, 3
        ),
        expected AS (
          SELECT s.contract_id, s.frequency, c.trade_date,
                 CASE WHEN s.frequency = 'minute' THEN c.expected_slots_1m ELSE 1 END
                   AS expected_records
          FROM (SELECT DISTINCT contract_id, frequency, root FROM {RECORDS}
                WHERE root IS NOT NULL) s
          JOIN {WINDOWS} w
            ON w.contract_id = s.contract_id AND w.frequency = s.frequency
          JOIN ref.session_calendar c
            ON c.root = s.root AND c.trade_date BETWEEN w.start_date AND w.end_date
          WHERE NOT c.is_holiday
            AND (w.roll_start IS NULL OR c.trade_date NOT BETWEEN w.roll_start AND w.roll_end)
            AND (s.frequency <> 'minute' OR c.expected_slots_1m IS NOT NULL)
        ),
        days AS (
          SELECT contract_id, frequency, trade_date FROM actual
          UNION
          SELECT contract_id, frequency, trade_date FROM expected
        ),
        defects AS (
          SELECT f.contract_id, f.frequency, f.trade_date, r.dimension,
                 count(DISTINCT f.record_id) AS affected_records
          FROM dq.dq_finding f
          JOIN dq.dq_rule r USING (rule_id)
          WHERE f.run_id = ? AND f.record_id IS NOT NULL AND f.severity IN ({severities})
          GROUP BY 1, 2, 3, 4
        ),
        counted AS (
          SELECT f.contract_id, f.frequency, f.trade_date, r.dimension,
                 count(*) AS finding_count
          FROM dq.dq_finding f
          JOIN dq.dq_rule r USING (rule_id)
          WHERE f.run_id = ?
          GROUP BY 1, 2, 3, 4
        ),
        grid AS (
          SELECT d.contract_id, d.frequency, d.trade_date, m.dimension,
                 coalesce(e.expected_records, 0) AS expected_records,
                 coalesce(a.actual_records, 0)   AS actual_records,
                 coalesce(x.affected_records, 0) AS affected_records,
                 coalesce(c.finding_count, 0)    AS finding_count
          FROM days d
          CROSS JOIN dims m
          LEFT JOIN actual a
            ON a.contract_id = d.contract_id AND a.frequency = d.frequency
           AND a.trade_date = d.trade_date
          LEFT JOIN expected e
            ON e.contract_id = d.contract_id AND e.frequency = d.frequency
           AND e.trade_date = d.trade_date
          LEFT JOIN defects x
            ON x.contract_id = d.contract_id AND x.frequency = d.frequency
           AND x.trade_date = d.trade_date AND x.dimension = m.dimension
          LEFT JOIN counted c
            ON c.contract_id = d.contract_id AND c.frequency = d.frequency
           AND c.trade_date = d.trade_date AND c.dimension = m.dimension
        )
        SELECT contract_id, trade_date, frequency, dimension,
               expected_records, actual_records, affected_records, finding_count,
               CASE WHEN dimension = 'completeness'
                    THEN 100.0 * least(1.0,
                           greatest(0, actual_records - affected_records)
                           / CAST(expected_records AS DOUBLE))
                    ELSE 100.0 * greatest(0.0,
                           1.0 - affected_records / CAST(actual_records AS DOUBLE))
               END AS dimension_score
        FROM grid
        WHERE (dimension = 'completeness' AND expected_records > 0)
           OR (dimension <> 'completeness' AND actual_records > 0)
        """,
        [*ALWAYS_IN_SCOPE, run_id, *DEFECT_SEVERITIES, run_id],
    ).fetchall()

    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO mart.dq_metric_daily
              (contract_id, trade_date, frequency, dimension, expected_records,
               actual_records, affected_records, finding_count, dimension_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def score_run(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
) -> list[SliceScore]:
    """Score every slice a run covered and persist the per-day metrics.

    Call inside `runner.scoped`, so the score is computed over exactly the record set and the
    windows the rules were evaluated against.
    """
    persist_daily_metrics(con, run_id)
    slices = con.execute(
        f"SELECT DISTINCT contract_id, frequency FROM {RECORDS} ORDER BY 1, 2"
    ).fetchall()
    return [
        score_slice(con, run_id, contract_id, frequency, min_records=min_records)
        for contract_id, frequency in slices
    ]
