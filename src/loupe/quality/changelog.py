"""The changelog: what default cleaning decided, read back as counts.

`dq.cleaning_action` has held these rows since slice 2 with no read path. They are the
evidence for locked decision 1 — raw records are immutable, the clean basis is derived, and
every number is reproducible from the source file plus the ruleset — so a UI that shows a
clean series without them is asking to be trusted rather than showing its working.

**Aggregated, not per record.** The Trader panel row is a count (`CMP.* 2025-06-12 excluded
4 open slots`), so returning one row per affected record would leave the widget summing them,
and aggregation is outside `ui` (solution brief §6). One row here is a rule × trade date ×
action, with how many records it touched.

Read-only. Nothing in this module writes a cleaning decision; `cleaning.apply_default_cleaning`
is the only author, and it acts on severity rather than on anything a user chose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb


@dataclass(frozen=True)
class ChangelogEntry:
    """One cleaning decision, summarised over the records it touched."""

    contract_id: str
    trade_date: date | None
    frequency: str | None
    rule_id: str | None
    label: str | None
    action: str
    records: int

    def as_json(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "trade_date": self.trade_date,
            "frequency": self.frequency,
            "rule_id": self.rule_id,
            "label": self.label,
            "action": self.action,
            "records": self.records,
        }


def latest_run(con: duckdb.DuckDBPyConnection) -> str | None:
    """The run the changelog defaults to, resolved as `/dq/summary` resolves it."""
    row = con.execute(
        "SELECT run_id FROM dq.dq_run WHERE status = 'succeeded' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else None


def changelog(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    *,
    contracts: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ChangelogEntry], int]:
    """Cleaning decisions for one run, as counts. Returns the page and the total row count.

    `dq.cleaning_action` carries neither `contract_id` nor `trade_date` — it keys on
    `record_id` — so both come from joining `stage.market_record`, which has them and is the
    only place they are authoritative. The join is also what scopes the changelog to a
    contract or a window at all.

    `dq.dq_rule.name` supplies the label so the wording lives with the rule rather than in a
    widget. A decision can carry a null `rule_id` in principle; it is kept and labelled null
    rather than dropped, because a cleaning action nobody can attribute is exactly the thing
    an audit trail should still show.
    """
    clauses = ["a.run_id = ?"]
    args: list[Any] = [run_id]
    if contracts:
        placeholders = ", ".join("?" for _ in contracts)
        clauses.append(f"m.contract_id IN ({placeholders})")
        args.extend(contracts)
    if start is not None:
        clauses.append("m.trade_date >= ?")
        args.append(start)
    if end is not None:
        clauses.append("m.trade_date <= ?")
        args.append(end)
    where = " AND ".join(clauses)

    grouped = f"""
        SELECT m.contract_id, m.trade_date, m.frequency, a.rule_id, r.name, a.action,
               count(*) AS records
        FROM dq.cleaning_action a
        JOIN stage.market_record m ON m.record_id = a.record_id
        LEFT JOIN dq.dq_rule r ON r.rule_id = a.rule_id
        WHERE {where}
        GROUP BY 1, 2, 3, 4, 5, 6
    """
    total = con.execute(f"SELECT count(*) FROM ({grouped})", args).fetchone()
    rows = con.execute(
        f"{grouped} ORDER BY m.trade_date DESC, m.contract_id, a.rule_id, a.action "
        "LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    entries = [
        ChangelogEntry(
            contract_id=r[0],
            trade_date=r[1],
            frequency=r[2],
            rule_id=r[3],
            label=r[4],
            action=r[5],
            records=int(r[6]),
        )
        for r in rows
    ]
    return entries, int(total[0]) if total else 0
