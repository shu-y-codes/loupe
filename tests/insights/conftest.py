"""Fixtures for the insights tests.

The same shape as the quality tests: a real fixture through the real ingest path, then the
real writer against a real in-memory DuckDB. The SQL is the logic in this layer too.
"""

from __future__ import annotations

import duckdb
import pytest

from loupe.data import LoadResult, load_file
from loupe.insights import BarBuildReport, build_bars
from loupe.quality import seed_quality


@pytest.fixture
def icon(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Schema, reference profiles and the rule catalogue — findings need seeded rules."""
    seed_quality(con)
    return con


@pytest.fixture
def load_and_build(icon: duckdb.DuckDBPyConnection, fixture_path):
    """Load one fixture and materialise its bars under both bases and both sources."""

    def _run(name: str, **kwargs) -> tuple[LoadResult, BarBuildReport]:
        batch = load_file(icon, fixture_path(name))
        return batch, build_bars(icon, **kwargs)

    return _run
