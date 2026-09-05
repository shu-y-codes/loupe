"""Purging one ingest batch, and everything downstream of it.

Uploads are the only way records enter the store, so a batch is the unit of undo. Purge is a
**soft delete**: the `stage.ingest_batch` row survives with `status = 'purged'` so ingest
history stays intact and a re-upload of the same bytes is still recognised as the duplicate
it is. Everything the batch *produced* is removed.

**One place owns the table list.** Which tables a purge touches is a fact about the storage
model, not about HTTP, so the route calls this and never spells the cascade out itself
(`plans/04-api.md` done-when 5). Adding a table downstream of ingest means editing this
function, and the test that asserts an unrelated batch survives is what catches a miss.

**Why the joins here are exact rather than inferential.** `plans/04-api.md` anticipated
reusing the span-overlap resolver `insights.gate` uses for `file`-scope findings. That
resolver exists because `dq.dq_finding` carries no `batch_id` and so cannot say which upload
produced it. The tables a purge touches are not in that position: `stage.market_record`
carries `batch_id` *and* `trade_date`, so "which sessions did this batch contribute to" is a
`GROUP BY`, and `dq.dq_run` carries `batch_id`, so "which findings came from a run over this
batch" is a join. Inferring from timestamp spans what a foreign key already states would be
less precise, not more. `insights` also sits above `data` in the layering
(`specs/loupe-solution-design.md` §6) and importing it here would invert that.

**What a purge deliberately does not delete.** Findings written by a corpus-wide run
(`dq.dq_run.batch_id IS NULL`) that are *about a session* rather than about a record survive,
because that session may hold another batch's records too and the finding is a statement
about all of them. The honest response to a changed corpus is to re-validate it —
`POST /v1/dq/runs` — not to guess which half of a statement to delete.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .errors import LoupeDataError


class BatchNotFound(LoupeDataError):
    """No such batch. The API surfaces this as 404."""

    def __init__(self, batch_id: str) -> None:
        super().__init__(f"no ingest batch {batch_id}")
        self.batch_id = batch_id


class BatchAlreadyPurged(LoupeDataError):
    """The batch has already been purged. Purge is idempotent to the caller; this says so."""

    def __init__(self, batch_id: str) -> None:
        super().__init__(f"batch {batch_id} is already purged")
        self.batch_id = batch_id


@dataclass(frozen=True)
class PurgeResult:
    """What the purge removed, per table, so the response can be specific."""

    batch_id: str
    records_deleted: int
    rejects_deleted: int
    findings_deleted: int
    bars_deleted: int
    sessions_affected: int

    @property
    def total_deleted(self) -> int:
        return (
            self.records_deleted
            + self.rejects_deleted
            + self.findings_deleted
            + self.bars_deleted
        )


def purge_batch(con: duckdb.DuckDBPyConnection, batch_id: str) -> PurgeResult:
    """Remove everything batch `batch_id` produced; keep the batch row as `purged`.

    Raises `BatchNotFound` for an unknown id and `BatchAlreadyPurged` for a repeat call —
    a second purge is not silently reported as having deleted a second copy of the rows.

    Derived bars for every session the batch touched are dropped rather than recomputed.
    A bar is a statement about a record set that no longer exists, so leaving it in place
    would be worse than removing it; rebuilding is `insights.build_bars`, and the caller
    decides when to run it.
    """
    status = con.execute(
        "SELECT status FROM stage.ingest_batch WHERE batch_id = ?", [batch_id]
    ).fetchone()
    if status is None:
        raise BatchNotFound(batch_id)
    if status[0] == "purged":
        raise BatchAlreadyPurged(batch_id)

    # The sessions this batch contributed to, resolved before its records are deleted.
    sessions = con.execute(
        "SELECT DISTINCT contract_id, frequency, trade_date FROM stage.market_record "
        "WHERE batch_id = ?",
        [batch_id],
    ).fetchall()

    findings = _delete_findings(con, batch_id)
    bars = _delete_bars(con, sessions)

    records = _delete(con, "DELETE FROM stage.market_record WHERE batch_id = ?", batch_id)
    rejects = _delete(con, "DELETE FROM stage.record_reject WHERE batch_id = ?", batch_id)

    con.execute(
        "UPDATE stage.ingest_batch SET status = 'purged', finished_at = now() "
        "WHERE batch_id = ?",
        [batch_id],
    )
    return PurgeResult(
        batch_id=batch_id,
        records_deleted=records,
        rejects_deleted=rejects,
        findings_deleted=findings,
        bars_deleted=bars,
        sessions_affected=len(sessions),
    )


def _delete(con: duckdb.DuckDBPyConnection, sql: str, *args: object) -> int:
    """Run a DELETE and report the row count, which DuckDB returns as a one-row result."""
    return int(con.execute(sql, list(args)).fetchone()[0])


def _delete_findings(con: duckdb.DuckDBPyConnection, batch_id: str) -> int:
    """Findings this batch is unambiguously responsible for.

    Two exact claims, not one inference: a run scoped to this batch, or a finding pinned to
    one of this batch's records by `record_id`. The module docstring says what is left alone
    and why.
    """
    return _delete(
        con,
        """
        DELETE FROM dq.dq_finding
        WHERE run_id IN (SELECT run_id FROM dq.dq_run WHERE batch_id = ?)
           OR record_id IN (SELECT record_id FROM stage.market_record WHERE batch_id = ?)
        """,
        batch_id,
        batch_id,
    )


def _delete_bars(
    con: duckdb.DuckDBPyConnection, sessions: list[tuple[str, str, object]]
) -> int:
    """Drop every bar over a session this batch fed, under both bases.

    `mart.bar_daily.source_frequency` is the grain a bar was built *from*, which is what the
    batch's own `frequency` names — so a purged daily upload drops the vendor bars it
    supplied and leaves bars derived from the minute tape for the same session standing.
    """
    if not sessions:
        return 0
    deleted = 0
    for contract_id, frequency, trade_date in sessions:
        deleted += _delete(
            con,
            "DELETE FROM mart.bar_daily WHERE contract_id = ? AND trade_date = ? "
            "AND source_frequency = ?",
            contract_id,
            trade_date,
            frequency,
        )
    return deleted
