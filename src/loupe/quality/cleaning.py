"""Default cleaning: severity in, decision rows out.

Raw records stay immutable (locked decision 1). A cleaning decision is a row in
`dq.cleaning_action`, and `dq.market_record_clean` is the view derived from those rows, so
every number in the application is reproducible from the source file plus the ruleset and the
changelog comes for free.

Default cleaning is **automatic policy, not a user action**. "Report-only" in v1 bounds what a
*user* may do to rules and findings; it does not mean the engine declines to clean. What the
engine does is decided by the finding's severity and by the two rules whose action is not the
severity default — which are read from the row, never from a branch here:

* `UNQ.EXACT_DUPLICATE` is `dedupe_drop` rather than `exclude`, keeping the lowest `source_row`.
* `VAL.OFF_TICK_PRICE` is flag-only even when it fires everywhere, because a systematic
  off-tick pattern is evidence about the tick reference and not about the price.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .catalogue import DEDUPE_DROP_RULES, NEVER_EXCLUDE_RULES

#: Severities whose default cleaning is `exclude` (spec §1). `critical` also blocks the
#: series; blocking is slice 3's job, so this slice records the exclusion only.
EXCLUDING_SEVERITIES = ("error", "critical")


@dataclass(frozen=True)
class CleaningReport:
    """What one cleaning pass decided."""

    excluded: int
    dedupe_dropped: int
    records_affected: int

    @property
    def total(self) -> int:
        return self.excluded + self.dedupe_dropped


def _in_list(values: frozenset[str]) -> tuple[str, list[str]]:
    if not values:
        return "FALSE", []
    ordered = sorted(values)
    return ", ".join("?" for _ in ordered), ordered


def apply_default_cleaning(
    con: duckdb.DuckDBPyConnection, run_id: str
) -> CleaningReport:
    """Write `dq.cleaning_action` rows for one run's findings.

    Idempotent by construction: a decision is keyed on `(record_id, rule_id, action)` and is
    not written twice, so re-running the same rules over the same records changes nothing and
    `dq.market_record_clean` is stable under repetition.
    """
    dedupe_placeholders, dedupe_args = _in_list(DEDUPE_DROP_RULES)
    never_placeholders, never_args = _in_list(NEVER_EXCLUDE_RULES)
    severities = ", ".join("?" for _ in EXCLUDING_SEVERITIES)

    written = con.execute(
        f"""
        INSERT INTO dq.cleaning_action (run_id, record_id, rule_id, action, rationale)
        SELECT ?, f.record_id, f.rule_id,
               CASE WHEN f.rule_id IN ({dedupe_placeholders}) THEN 'dedupe_drop'
                    ELSE 'exclude' END AS action,
               'default cleaning policy for ' || f.severity || ' finding on ' || f.rule_id
        FROM dq.dq_finding f
        WHERE f.run_id = ?
          AND f.record_id IS NOT NULL
          AND (
                f.rule_id IN ({dedupe_placeholders})
                OR (f.severity IN ({severities})
                    AND f.rule_id NOT IN ({never_placeholders}))
              )
          AND NOT EXISTS (
            SELECT 1 FROM dq.cleaning_action a
            WHERE a.record_id = f.record_id
              AND a.rule_id = f.rule_id
              AND a.action = CASE WHEN f.rule_id IN ({dedupe_placeholders})
                                  THEN 'dedupe_drop' ELSE 'exclude' END
          )
        RETURNING action, record_id
        """,
        [
            run_id,
            *dedupe_args,
            run_id,
            *dedupe_args,
            *EXCLUDING_SEVERITIES,
            *never_args,
            *dedupe_args,
        ],
    ).fetchall()

    excluded = sum(1 for action, _ in written if action == "exclude")
    dropped = sum(1 for action, _ in written if action == "dedupe_drop")
    return CleaningReport(
        excluded=excluded,
        dedupe_dropped=dropped,
        records_affected=len({record_id for _, record_id in written}),
    )


def exclusion_rate(con: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """`n` of `N` records excluded, split by rule and by root.

    Measured rather than asserted: the first exclusion is the one nobody has seen the
    consequences of, and a quirk that trips one rule on a few percent of one root would
    surface downstream as an aggregation bug rather than as a data defect (spec §17).
    """
    total = int(con.execute("SELECT count(*) FROM stage.market_record").fetchone()[0])
    excluded = int(
        con.execute(
            """
            SELECT count(DISTINCT record_id) FROM dq.cleaning_action
            WHERE action IN ('exclude', 'dedupe_drop')
            """
        ).fetchone()[0]
    )
    by_rule = con.execute(
        """
        SELECT rule_id, action, count(DISTINCT record_id) AS records
        FROM dq.cleaning_action
        WHERE action IN ('exclude', 'dedupe_drop')
        GROUP BY 1, 2
        ORDER BY records DESC, rule_id
        """
    ).fetchall()
    by_root = con.execute(
        """
        SELECT c.root, r.frequency,
               count(DISTINCT a.record_id) AS excluded,
               count(DISTINCT r.record_id) AS records
        FROM stage.market_record r
        LEFT JOIN ref.contract c ON c.contract_id = r.contract_id
        LEFT JOIN dq.cleaning_action a
               ON a.record_id = r.record_id AND a.action IN ('exclude', 'dedupe_drop')
        GROUP BY 1, 2
        ORDER BY excluded DESC, c.root
        """
    ).fetchall()
    return {
        "records": total,
        "excluded": excluded,
        "excluded_pct": round(100.0 * excluded / total, 6) if total else 0.0,
        "by_rule": [
            {"rule_id": rule_id, "action": action, "records": int(records)}
            for rule_id, action, records in by_rule
        ],
        "by_root": [
            {
                "root": root,
                "frequency": frequency,
                "excluded": int(excluded_n),
                "records": int(records),
                "excluded_pct": round(100.0 * excluded_n / records, 6) if records else 0.0,
            }
            for root, frequency, excluded_n, records in by_root
        ],
    }
