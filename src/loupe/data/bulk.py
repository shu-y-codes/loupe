"""Writing many rows at once, for the rows that genuinely originate in Python.

Most of this application never needs it: records are written straight from the scan
(`load._insert_records`) and daily metrics straight from the query that computes them, both as
`INSERT ... SELECT` with no round trip at all. That is the idiom, and it should stay the first
thing anyone reaches for.

Some rows have no query behind them. A `Finding` is returned by a rule runner as a Python
object, and there is no SELECT that produces it. For those, the choice is between one statement
per row and one statement per chunk — and on DuckDB that is not a small difference. Measured
over 145,236 rows:

| how | time |
|---|---|
| `executemany`, `INSERT OR REPLACE` into a table with a composite key | 86.4s |
| `executemany`, plain `INSERT` with no key to probe | 16.9s |
| chunked multi-row `VALUES` (this module) | 2.0s |
| `INSERT ... SELECT`, no Python round trip | ~0.0s |

Two separate costs, which is why the numbers do not simply halve: a per-row round trip, and —
where the target has a key — a per-row index probe, possible delete and insert. Chunking removes
the first and lets the engine amortise the second.

`specs/data-model.md` §5 carries the rule this module exists to keep.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb

#: Rows per statement. Large enough that the per-statement cost stops mattering, small enough
#: that the parameter list stays sane — 5,000 measured no faster than 500, so this is the
#: conservative end of a flat curve rather than a tuned figure.
CHUNK = 1000


def insert_rows(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    replace: bool = False,
) -> int:
    """Insert `rows` into `table`, one statement per chunk. Returns the number written.

    `table` and `columns` are composed into SQL, so they are the caller's own literals and never
    user input — every call site in this repository passes a constant. Values are always bound.

    `replace` selects `INSERT OR REPLACE`, which needs a key on the target and makes a re-run
    idempotent rather than duplicating.
    """
    if not rows:
        return 0
    width = len(columns)
    for index, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(
                f"{table}: row {index} has {len(row)} values for {width} columns {tuple(columns)}"
            )

    verb = "INSERT OR REPLACE INTO" if replace else "INSERT INTO"
    prefix = f"{verb} {table} ({', '.join(columns)}) VALUES "
    placeholder = "(" + ", ".join("?" * width) + ")"

    written = 0
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start : start + CHUNK]
        con.execute(
            prefix + ", ".join([placeholder] * len(chunk)),
            [value for row in chunk for value in row],
        )
        written += len(chunk)
    return written
