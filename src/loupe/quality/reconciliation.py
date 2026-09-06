"""The reconcilable session frame — which sessions can be compared, and what they compare to.

Three things need this and none of them is the others' business, which is why it is a module
rather than a helper inside one of them. The `REC.*` runners write findings from it
(`rules/reconciliation.py`); the scorer takes §8.6's denominator from it (`scoring.py`); and
`corroboration.py` reads the same sessions back to say whether the tape confirms a daily
finding. A frame computed three times would be free to disagree with itself about which
sessions were comparable, and the disagreement would surface as a score that does not match
the findings under it.

**Both grains or nothing.** The frame inner-joins the two coverage windows, so a contract
holding one granularity produces no rows at all — not zero rows meaning "nothing wrong", but
no rows meaning "not asked". Everything downstream reads absence that way: §8.6 gives such a
contract *no* reconciliation score, and §8.7 answers `not_comparable` rather than `confirmed`.

**Derived bars are built the way `insights.bars` builds them**, positionally on
`(ts_utc, source_row)` for `open` and `close` and extremally for `high` and `low`
(`specs/analytics-semantics.md` §3.1). This module aggregates the scoped record set directly
rather than reading `mart.bar_daily`, because a rule pass must compare the records it is
evaluating — a mart built before the run would answer for a different corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from .registry import RECORDS, WINDOWS

#: `mart.dq_metric_daily.frequency` for the reconciliation rollup (§11.1). Not a finding's
#: frequency: a finding is a statement about one side, while this row is about the pair.
CROSS = "cross"

#: The two rules whose evidence makes a session *defective* for §8.6. `REC.CLOSE_CONVENTION`
#: is absent because it is `info` and §8.4 keeps it out of the numerator, and
#: `REC.SESSION_ONLY_IN_ONE` because a session present at one granularity is by definition not
#: in the denominator — counting it could drive the sub-score below zero.
DEFECT_RULES: tuple[str, ...] = ("REC.OHLC_DISAGREE", "REC.VOLUME_SHORTFALL")

# DuckDB's arg_min / arg_max skip rows whose *value* is null, which is not the definition
# `specs/analytics-semantics.md` §3.1 asks for. Wrapping the value in a struct makes it
# non-null, so the row is considered and the null comes back. Identical to `insights.bars`.
_FIRST = "arg_min({{'v': r.{col}}}, {{'t': r.ts_utc, 'r': r.source_row}}).v"
_LAST = "arg_max({{'v': r.{col}}}, {{'t': r.ts_utc, 'r': r.source_row}}).v"


def session_frame_sql(records: str = RECORDS, windows: str = WINDOWS) -> str:
    """One row per `(contract_id, trade_date)` a reconciliation rule may look at.

    Columns: the derived side, the vendor side, the coverage the comparison rests on, and
    `in_window` — whether the session falls inside the reconcilable window of §8.5, which is
    the intersection of the two coverage windows. Sessions outside it are still returned, with
    the flag false, because `REC.SESSION_ONLY_IN_ONE` is the one rule that has to know the
    difference between "absent inside the window" and "absent outside it".

    Coverage is measured against `ref.session_calendar.expected_slots_1m` — the **calendar's**
    expected slots and never a maximum inferred from the upload (§8.1). A file that is short
    everywhere would otherwise define its own shortfall away.
    """
    return f"""
    WITH recon_window AS (
      SELECT m.contract_id,
             greatest(m.start_date, d.start_date) AS start_date,
             least(m.end_date, d.end_date)        AS end_date
      FROM {windows} m
      JOIN {windows} d ON d.contract_id = m.contract_id
      WHERE m.frequency = 'minute' AND d.frequency = 'daily'
    ),
    derived AS (
      SELECT r.contract_id, r.trade_date, any_value(r.root) AS root,
             {_FIRST.format(col="open")}   AS derived_open,
             max(r.high)                   AS derived_high,
             min(r.low)                    AS derived_low,
             {_LAST.format(col="close")}   AS derived_close,
             sum(r.volume)                 AS derived_volume,
             count(*)                      AS minute_records,
             min(r.ts_utc)                 AS first_ts_utc,
             max(r.ts_utc)                 AS last_ts_utc
      FROM {records} r
      WHERE r.frequency = 'minute'
      GROUP BY 1, 2
    ),
    vendor AS (
      SELECT r.contract_id, r.trade_date, any_value(r.root) AS root,
             count(*) AS vendor_rows,
             -- The lowest source row wins where a session carries more than one daily record.
             -- Two different settlements for one session is `UNQ.KEY_CONFLICT`'s finding to
             -- write, not this frame's; picking deterministically keeps the comparison
             -- reproducible instead of letting row order decide it.
             arg_min({{'record_id': r.record_id, 'open': r.open, 'high': r.high,
                       'low': r.low, 'close': r.close, 'volume': r.volume,
                       'ts_utc': r.ts_utc}}, r.source_row) AS v
      FROM {records} r
      WHERE r.frequency = 'daily'
      GROUP BY 1, 2
    ),
    paired AS (
      SELECT coalesce(d.contract_id, v.contract_id) AS contract_id,
             coalesce(d.trade_date, v.trade_date)   AS trade_date,
             coalesce(d.root, v.root)               AS root,
             d.derived_open, d.derived_high, d.derived_low, d.derived_close,
             d.derived_volume, d.minute_records, d.first_ts_utc, d.last_ts_utc,
             v.vendor_rows,
             v.v.record_id AS vendor_record_id,
             v.v.open      AS vendor_open,
             v.v.high      AS vendor_high,
             v.v.low       AS vendor_low,
             v.v.close     AS vendor_close,
             v.v.volume    AS vendor_volume,
             v.v.ts_utc    AS vendor_ts_utc
      FROM derived d
      FULL OUTER JOIN vendor v
        ON v.contract_id = d.contract_id AND v.trade_date = d.trade_date
    )
    SELECT p.*,
           sc.expected_slots_1m AS expected_slots,
           CASE WHEN sc.expected_slots_1m IS NULL OR sc.expected_slots_1m = 0 THEN NULL
                ELSE p.minute_records / CAST(sc.expected_slots_1m AS DOUBLE) END
             AS coverage_pct,
           p.minute_records IS NOT NULL   AS has_minute,
           p.vendor_record_id IS NOT NULL AS has_daily,
           p.trade_date BETWEEN w.start_date AND w.end_date AS in_window
    FROM paired p
    JOIN recon_window w ON w.contract_id = p.contract_id
    LEFT JOIN ref.contract c ON c.contract_id = p.contract_id
    LEFT JOIN ref.session_calendar sc
      ON sc.exchange = c.exchange AND sc.root = c.root AND sc.trade_date = p.trade_date
    """


def reconcilable_sql(records: str = RECORDS, windows: str = WINDOWS) -> str:
    """§8.6's denominator: sessions present at **both** frequencies, inside the window.

    Sessions, not records — the comparison is session-grained, and one daily row against 1,380
    minute rows has no record-level denominator that means anything.
    """
    return f"""
    SELECT contract_id, trade_date, root, coverage_pct, expected_slots, minute_records
    FROM ({session_frame_sql(records, windows)})
    WHERE has_minute AND has_daily AND in_window
    """


def settlement_marks(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Per-root settlement marks, from `REC.CLOSE_CONVENTION`'s seeded row (§8.4).

    One copy, read by both rules that need it. `REC.CLOSE_CONVENTION` decides that a close
    difference *is* a convention difference and `REC.OHLC_DISAGREE` decides that it is not, so
    they must agree about where the mark is; two seeded copies could disagree and leave a
    session that is neither, which is the one outcome §8.4 exists to prevent. The mark lives on
    the rule whose subject it is, and the other reads it.

    An unseeded or disabled rule yields an empty map, and the close comparison then stands down
    on every root rather than falling back to a default nobody chose.
    """
    row = con.execute(
        "SELECT params->>'settlement_mark_local' FROM dq.dq_rule "
        "WHERE rule_id = 'REC.CLOSE_CONVENTION' AND enabled"
    ).fetchone()
    if not row or row[0] is None:
        return {}
    marks = json.loads(row[0])
    return {str(k): str(v) for k, v in marks.items()} if isinstance(marks, dict) else {}


def mark_for(marks: dict[str, str], root: str | None) -> str | None:
    """The mark for one root: its own, else the default, else none."""
    if root and root in marks:
        return marks[root]
    return marks.get("default")


@dataclass(frozen=True)
class SessionEvidence:
    """One reconcilable session, as the scorer and the mart rollup read it."""

    contract_id: str
    trade_date: date
    coverage_pct: float | None
    expected_slots: int | None
    minute_records: int
    defect_findings: int
    findings: int

    @property
    def is_defect(self) -> bool:
        return self.defect_findings > 0


def reconciliation_evidence(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    *,
    contract_id: str | None = None,
    exclude_rule: str | None = None,
    records: str = RECORDS,
    windows: str = WINDOWS,
) -> list[SessionEvidence]:
    """Every reconcilable session and the `REC.*` findings sitting on it.

    Call inside `runner.scoped`: the frame is built over the scoped record set and the shared
    windows, so the sessions counted here are exactly the sessions the rules were evaluated
    over. The defect count is restricted to `DEFECT_RULES` at defect severity, which is what
    keeps `REC.CLOSE_CONVENTION` out of §8.6's numerator by construction rather than by a
    reader remembering to exclude it.

    `exclude_rule` is the dry-run of §11.4: the same evidence with one rule's findings set
    aside, so the worklist can say what resolving *that* rule would recover. Without it a
    reconciliation rule's dry-run would show no movement at all and read as "fixing this
    changes nothing".
    """
    defect_rules = ", ".join("?" for _ in DEFECT_RULES)
    clause, args = ("TRUE", [])
    if contract_id is not None:
        clause, args = ("s.contract_id = ?", [contract_id])
    rows = con.execute(
        f"""
        WITH sessions AS ({reconcilable_sql(records, windows)}),
        rec AS (
          SELECT f.contract_id, f.trade_date,
                 count(*) AS findings,
                 count(*) FILTER (
                   WHERE f.rule_id IN ({defect_rules})
                     AND f.severity IN ('warning', 'error', 'critical')
                 ) AS defect_findings
          FROM dq.dq_finding f
          WHERE f.run_id = ? AND f.rule_id LIKE 'REC.%'
            AND (? IS NULL OR f.rule_id <> ?)
          GROUP BY 1, 2
        )
        SELECT s.contract_id, s.trade_date, s.coverage_pct, s.expected_slots,
               s.minute_records,
               coalesce(r.defect_findings, 0), coalesce(r.findings, 0)
        FROM sessions s
        LEFT JOIN rec r ON r.contract_id = s.contract_id AND r.trade_date = s.trade_date
        WHERE {clause}
        ORDER BY 1, 2
        """,
        [*DEFECT_RULES, run_id, exclude_rule, exclude_rule, *args],
    ).fetchall()
    return [
        SessionEvidence(
            contract_id=row[0],
            trade_date=row[1],
            coverage_pct=None if row[2] is None else float(row[2]),
            expected_slots=None if row[3] is None else int(row[3]),
            minute_records=int(row[4] or 0),
            defect_findings=int(row[5]),
            findings=int(row[6]),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class ReconciliationScore:
    """§8.6's sub-score for one contract, or the reason there is none.

    `score` is `None` and `reason` is set together: a contract with no reconcilable sessions
    gets **no** reconciliation score — not 100, not 0 — because both would be claims about
    evidence that does not exist.
    """

    contract_id: str
    reconcilable_sessions: int
    defect_sessions: int
    score: float | None
    reason: str | None
    #: Every `REC.*` finding on the contract, both sides. The dimension is about the *pair*,
    #: so counting it per slice frequency would report the shortfalls on the minute slice and
    #: the disagreements on the daily one while both slices show the same score.
    finding_count: int = 0

    def as_json(self) -> dict[str, Any]:
        return {
            "reconcilable_sessions": self.reconcilable_sessions,
            "defect_sessions": self.defect_sessions,
            "score": self.score,
            "reason": self.reason,
            "finding_count": self.finding_count,
        }


def reconciliation_score(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    *,
    exclude_rule: str | None = None,
    records: str = RECORDS,
    windows: str = WINDOWS,
) -> ReconciliationScore:
    """`100 × (1 − defect_sessions / reconcilable_sessions)`, or the reason it is undefined.

    The denominator counts sessions the two files both hold inside the reconcilable window,
    which is why a contract can hold both granularities and still have no score: two files
    whose date spans do not overlap have nothing to compare.
    """
    evidence = reconciliation_evidence(
        con,
        run_id,
        contract_id=contract_id,
        exclude_rule=exclude_rule,
        records=records,
        windows=windows,
    )
    findings = _rec_finding_count(con, run_id, contract_id, exclude_rule=exclude_rule)
    if not evidence:
        return ReconciliationScore(
            contract_id=contract_id,
            reconcilable_sessions=0,
            defect_sessions=0,
            score=None,
            reason=_no_evidence_reason(con, contract_id, records=records),
            finding_count=findings,
        )
    defects = sum(1 for session in evidence if session.is_defect)
    return ReconciliationScore(
        contract_id=contract_id,
        reconcilable_sessions=len(evidence),
        defect_sessions=defects,
        score=round(100.0 * (1.0 - defects / len(evidence)), 4),
        reason=None,
        finding_count=findings,
    )


def _rec_finding_count(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    contract_id: str,
    *,
    exclude_rule: str | None = None,
) -> int:
    row = con.execute(
        """
        SELECT count(*) FROM dq.dq_finding
        WHERE run_id = ? AND contract_id = ? AND rule_id LIKE 'REC.%'
          AND (? IS NULL OR rule_id <> ?)
        """,
        [run_id, contract_id, exclude_rule, exclude_rule],
    ).fetchone()
    return int(row[0]) if row else 0


def _no_evidence_reason(
    con: duckdb.DuckDBPyConnection, contract_id: str, *, records: str = RECORDS
) -> str:
    """Why this contract has no reconciliation score — a statement about **its data**.

    Rendered verbatim under the score (`specs/loupe-ui-design.md`), so it must never carry a
    note about the build sequence: a reader takes what is printed there as a fact about their
    contract.
    """
    row = con.execute(
        f"SELECT count(DISTINCT frequency) FROM {records} WHERE contract_id = ?",
        [contract_id],
    ).fetchone()
    if not row or int(row[0]) <= 1:
        return "only one frequency uploaded for this contract"
    return (
        "both frequencies are held, but no session is present in both inside the window "
        "where they overlap, so there is nothing to reconcile"
    )
