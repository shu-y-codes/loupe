"""Shared test fixtures.

Every test runs against a real in-memory DuckDB rather than a mock: the SQL *is* the logic
here, and a mocked connection would assert that we wrote the query we wrote.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from loupe.data import apply_schema, connect, seed_reference

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SAMPLES = REPO_ROOT / "data" / "samples"


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    """An empty database with the schema applied and reference profiles seeded."""
    connection = connect(":memory:")
    apply_schema(connection)
    seed_reference(connection)
    yield connection
    connection.close()


@pytest.fixture
def bare_con() -> duckdb.DuckDBPyConnection:
    """A connection with no schema, for testing schema application itself."""
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def fixture_path():
    def _path(name: str) -> Path:
        path = FIXTURES / name
        assert path.exists(), f"missing fixture {name}"
        return path

    return _path


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """The fetched vendor corpus, or a skip when it is absent.

    The corpus carries no redistribution licence, so it is never committed and these tests
    are optional by design (`specs/sample-corpus.md` §1).
    """
    present = (SAMPLES / "files.csv").exists()
    # #region agent log
    import json
    import time

    with open("/Users/shu/Documents/loupe/.cursor/debug-b987ef.log", "a") as _df:
        _df.write(json.dumps({
            "sessionId": "b987ef",
            "runId": "post-fix",
            "hypothesisId": "H4",
            "location": "tests/conftest.py:samples_dir",
            "message": "samples_dir session fixture",
            "timestamp": int(time.time() * 1000),
            "data": {
                "samples": str(SAMPLES),
                "files_csv_exists": present,
                "will_skip": not present,
            },
        }) + "\n")
    # #endregion
    if not present:
        pytest.skip("data/samples/ not fetched; run python tools/fetch_samples.py")
    return SAMPLES
