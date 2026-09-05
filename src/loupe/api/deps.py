"""The database dependency, and the shared query parameters the contract defines once.

**One connection, serialised.** `specs/api-contract.md` §4.4 settles the concurrency model:
single user, local DuckDB, every endpoint synchronous. So the app holds one connection and a
lock rather than a pool. FastAPI runs non-`async` handlers in a threadpool, so without the
lock two requests could drive one DuckDB connection at once — and the quality runner
materialises named working tables (`dq_scope_records`) that a second concurrent run would
drop from under the first. Serialising is not a performance compromise here; it is the
assumption the contract already committed to.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date
from typing import Annotated

import duckdb
from fastapi import Depends, Query, Request

#: `basis` and `frequency` are spelled once here so every endpoint that takes them agrees on
#: the vocabulary and on the OpenAPI description (`specs/api-contract.md` §2).
BasisParam = Annotated[
    str,
    Query(
        pattern="^(raw|clean)$",
        description="Which record set to read: `raw` as supplied, or `clean` with the "
        "cleaning actions of the last run applied.",
    ),
]

FrequencyParam = Annotated[
    str | None,
    Query(
        pattern="^(minute|daily)$",
        description="Record grain to read *from*, not the grain returned. Omit to default "
        "to the finest granularity held for the contracts in scope.",
    ),
]

StartDateParam = Annotated[
    date | None,
    Query(description="Inclusive start **trade date** (session date, never a calendar date)."),
]

EndDateParam = Annotated[
    date | None,
    Query(description="Inclusive end **trade date** (session date, never a calendar date)."),
]

LimitParam = Annotated[int, Query(ge=1, le=1000, description="Page size; max 1000.")]
OffsetParam = Annotated[int, Query(ge=0, description="Rows to skip.")]


class Database:
    """The app's single connection, plus the lock that keeps one request on it at a time."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection
        self._lock = threading.Lock()

    def acquire(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            yield self._connection


def get_con(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield the connection for the duration of one request, holding the lock throughout."""
    database: Database = request.app.state.database
    yield from database.acquire()


Con = Annotated[duckdb.DuckDBPyConnection, Depends(get_con)]
