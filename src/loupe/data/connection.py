"""DuckDB connection factory.

One factory, one place that knows where the database lives and which extensions are
required. `icu` is not optional: every `AT TIME ZONE` expression in the ingest path needs
it, and the ingest path is where `ts_utc` is derived (locked decision 2).
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "loupe.duckdb"


def database_path() -> Path:
    """Where the analytics store lives. `LOUPE_DB` overrides; `:memory:` is honoured."""
    env = os.environ.get("LOUPE_DB")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def connect(
    path: str | Path | None = None,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Open the analytics store with the extensions Loupe requires.

    Pass `":memory:"` for tests. The parent directory is created for file-backed stores.
    """
    target = Path(path) if path is not None else database_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(target), read_only=read_only)
    _require_icu(con)
    # UTC on the wire, and a deterministic session whatever the host clock is set to. Local
    # time is still the source of truth for session logic; it is carried in ts_exchange.
    con.execute("SET TimeZone = 'UTC'")
    return con


def _require_icu(con: duckdb.DuckDBPyConnection) -> None:
    """Load `icu`, installing it once if the local extension store lacks it."""
    try:
        con.execute("LOAD icu")
        return
    except duckdb.Error:
        pass
    try:
        con.execute("INSTALL icu")
        con.execute("LOAD icu")
    except duckdb.Error as exc:  # pragma: no cover - depends on network/extension store
        raise RuntimeError(
            "DuckDB's icu extension is required for AT TIME ZONE conversions and could not "
            "be installed. Run `INSTALL icu` once with network access, or set the DuckDB "
            "extension directory to a writable location."
        ) from exc
