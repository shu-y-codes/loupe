"""Query helpers for the quality tests.

A module rather than fixtures: these are plain functions over a connection, and reading a
test is easier when `findings(con, run_id, "CON.HIGH_LT_LOW")` is a call rather than a
fixture the signature has to carry.
"""

from __future__ import annotations

import json
from typing import Any

import duckdb


def findings(
    con: duckdb.DuckDBPyConnection, run_id: str, rule_id: str
) -> list[dict[str, Any]]:
    """Every finding one rule wrote in one run, ordered as the engine emitted them."""
    rows = con.execute(
        """
        SELECT rule_id, contract_id, frequency, trade_date, ts_start_utc, ts_end_utc,
               record_id, affected_rows, severity, CAST(details AS VARCHAR), status
        FROM dq.dq_finding
        WHERE run_id = ? AND rule_id = ?
        ORDER BY coalesce(record_id, 0), ts_start_utc, trade_date
        """,
        [run_id, rule_id],
    ).fetchall()
    return [
        {
            "rule_id": row[0],
            "contract_id": row[1],
            "frequency": row[2],
            "trade_date": row[3],
            "ts_start_utc": row[4],
            "ts_end_utc": row[5],
            "record_id": row[6],
            "affected_rows": row[7],
            "severity": row[8],
            "details": json.loads(row[9]) if row[9] else {},
            "status": row[10],
        }
        for row in rows
    ]


def source_rows(con: duckdb.DuckDBPyConnection, record_ids: list[int]) -> list[int]:
    """The source file rows a set of record ids came from — the traceability spine."""
    if not record_ids:
        return []
    placeholders = ", ".join("?" for _ in record_ids)
    return [
        int(row[0])
        for row in con.execute(
            f"SELECT source_row FROM stage.market_record WHERE record_id IN ({placeholders})"
            " ORDER BY source_row",
            record_ids,
        ).fetchall()
    ]


def set_param(
    con: duckdb.DuckDBPyConnection, rule_id: str, name: str, value: Any
) -> None:
    """Change one seeded threshold, the way a deployment would.

    Used to prove a runner reads its params from the row rather than carrying a literal: if
    the behaviour does not move when the row does, the threshold is hard-coded somewhere.
    """
    current = json.loads(
        con.execute(
            "SELECT CAST(params AS VARCHAR) FROM dq.dq_rule WHERE rule_id = ?", [rule_id]
        ).fetchone()[0]
    )
    current[name] = value
    con.execute(
        "UPDATE dq.dq_rule SET params = ? WHERE rule_id = ?",
        [json.dumps(current, sort_keys=True), rule_id],
    )
