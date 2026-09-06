"""Fixtures for the quality tests.

Every test loads a real fixture through the real ingest path and then runs the real engine
against a real in-memory DuckDB. The SQL *is* the logic in this layer, so a mocked connection
would only assert that we wrote the query we wrote.
"""

from __future__ import annotations

import duckdb
import pytest

from loupe.data import LoadResult, load_file
from loupe.quality import RunResult, run_rules


@pytest.fixture
def run_fixture(qcon: duckdb.DuckDBPyConnection, fixture_path):
    """Load one fixture CSV and run the rule engine over exactly that batch."""

    def _run(
        name: str,
        *,
        rule_ids: tuple[str, ...] | None = None,
        clean: bool = True,
    ) -> tuple[LoadResult, RunResult]:
        batch = load_file(qcon, fixture_path(name))
        result = run_rules(qcon, batch_id=batch.batch_id, rule_ids=rule_ids, clean=clean)
        return batch, result

    return _run


@pytest.fixture
def run_fixture_with_bars(qcon: duckdb.DuckDBPyConnection, fixture_path):
    """Load a fixture, materialise `mart.bar_daily`, then run the rules over that batch.

    `CON.DERIVED_BAR_INVALID` reads bar provenance, so it refuses on a pass with no bars.
    Building them between the load and the run is the ordering the rule expects, and the
    refusal on the first pass is asserted in its own test rather than worked around here.
    """
    from loupe.insights import build_bars

    def _run(
        name: str,
        *,
        rule_ids: tuple[str, ...] | None = None,
        clean: bool = True,
    ) -> tuple[LoadResult, RunResult]:
        batch = load_file(qcon, fixture_path(name))
        if clean:
            run_rules(qcon, batch_id=batch.batch_id, clean=True)
        build_bars(qcon)
        result = run_rules(qcon, batch_id=batch.batch_id, rule_ids=rule_ids, clean=clean)
        return batch, result

    return _run
