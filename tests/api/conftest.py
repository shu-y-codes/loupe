"""Fixtures for the API contract tests.

The app is built over the same real in-memory DuckDB the other layers' tests use, not over
mocks. These are *contract* tests: they assert the envelope, the status code and the error
vocabulary `specs/api-contract.md` fixes, and they can only do that if the handler really
called the layer underneath.
"""

from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from loupe.api import create_app
from loupe.quality import seed_quality


@pytest.fixture
def api_con(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Schema, reference profiles and the seeded rule catalogue."""
    seed_quality(con)
    return con


@pytest.fixture
def client(api_con: duckdb.DuckDBPyConnection) -> TestClient:
    """A client over an app sharing the test's connection, so tests can inspect the store."""
    with TestClient(create_app(api_con)) as test_client:
        yield test_client


@pytest.fixture
def upload(client: TestClient, fixture_path):
    """POST one fixture to `/v1/ingest/batches` and hand back the response."""

    def _upload(name: str, *, validate: bool = True):
        path = fixture_path(name)
        with path.open("rb") as handle:
            return client.post(
                "/v1/ingest/batches",
                files={"file": (path.name, handle, "text/csv")},
                params={"validate": validate},
            )

    return _upload
