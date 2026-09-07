"""Fixtures for the UI tier (`specs/loupe-solution-design.md` §13).

Pages are driven by `streamlit.testing.v1.AppTest` over a **stubbed client**, so these tests
assert view assembly and never reach DuckDB. That is the point of the tier: a page test that
needed a database would be re-testing `quality`, and one that needed a live server could not
run in CI at all.

The stub is the seam done-when 3 created. Because `ui.runtime.get_client()` is the single
place the pages resolve a client, one `use_client()` call puts a fake in front of every panel.
"""

from __future__ import annotations

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from ui_helpers import APP, FakeClient

from loupe.ui import runtime


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient()


@pytest.fixture
def app(fake: FakeClient):
    """An `AppTest` over the real page with the stub in front of it."""

    def _run(client: FakeClient | None = None, **session: Any):
        runtime.use_client(client or fake)
        test = AppTest.from_file(APP, default_timeout=30)
        for key, value in session.items():
            test.session_state[key] = value
        return test.run()

    yield _run
    runtime.use_client(None)
