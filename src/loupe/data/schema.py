"""Apply the Loupe schema.

The DDL lives in `ddl.sql` as SQL rather than as generated strings: it is the artefact a
reviewer reads next to `specs/data-model.md`, and the two should be comparable line for line.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

DDL_PATH = Path(__file__).with_name("ddl.sql")

SCHEMAS = ("ref", "stage", "dq", "mart")


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create every schema, table, index and view. Idempotent."""
    con.execute(DDL_PATH.read_text())


def schema_is_applied(con: duckdb.DuckDBPyConnection) -> bool:
    """True when the four schemas exist. Cheap enough to call on connect."""
    rows = con.execute(
        "SELECT count(DISTINCT schema_name) FROM information_schema.schemata "
        "WHERE schema_name IN (?, ?, ?, ?)",
        list(SCHEMAS),
    ).fetchone()
    return bool(rows and rows[0] == len(SCHEMAS))
