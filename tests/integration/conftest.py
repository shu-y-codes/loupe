"""Fixtures for the integration tier — a real server, over a real file on disk.

Every other tier in this repo stops at a seam. `tests/api/` runs HTTP in-process through
`TestClient` and is handed a connection somebody already applied the schema to; `web/` drives
the React pages over a stubbed `fetch` that never opens a socket. Both are the right shape for
what they test, and between them they leave two things unexercised — the ones a first run
breaks on:

- **a store nobody has bootstrapped**, because every other fixture hands the app a database
  that is already set up;
- **the wire between `loupe.client` and the API**, because one side is always simulated.

So this tier simulates neither. It boots uvicorn on a real socket over a real DuckDB file and
talks to it with a real `LoupeClient`. It is deliberately small: these tests are slow, and
their job is to cover seams rather than behaviour the faster tiers already own.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
import uvicorn

from loupe.api import create_app
from loupe.client import LoupeClient
from loupe.data import connect

#: How long to wait for the server thread to bind. Generous: a loaded CI box is slow, and a
#: flaky integration tier gets muted, which is worse than not having one.
STARTUP_TIMEOUT = 20.0
SHUTDOWN_TIMEOUT = 10.0


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A path to a DuckDB file that does **not** exist yet.

    A path rather than a connection, and empty rather than seeded, because "what happens on a
    database nobody has set up" is the question this tier exists to ask.
    """
    return tmp_path / "loupe.duckdb"


@pytest.fixture
def cold_store(store_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """An open connection to a brand-new file: extensions loaded, and no schema at all."""
    connection = connect(store_path)
    yield connection
    connection.close()


def _serve(app) -> Iterator[str]:
    """Run `app` on an ephemeral port in a background thread; yield its base URL.

    A thread rather than a subprocess. DuckDB takes a write lock on the file, so a second
    process could not open the same store, and the point of this tier is that the server and
    the test share one — the test asserts over HTTP and reads the file only after.

    Port 0 lets the OS pick, so two runs of this tier never collide.
    """
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + STARTUP_TIMEOUT
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            raise RuntimeError("the API did not start within the timeout")
        if not thread.is_alive():
            raise RuntimeError("the API thread died during startup")
        time.sleep(0.02)

    sock: socket.socket = server.servers[0].sockets[0]
    port = sock.getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=SHUTDOWN_TIMEOUT)


@pytest.fixture
def live_api(store_path: Path, monkeypatch) -> Iterator[str]:
    """A bootstrapped API on a real socket, over a real file. Yields the base URL.

    `bootstrap=True` is the documented way to start against an empty store, so this is the
    path the README's `uvicorn` command takes rather than a setup the tests invented.

    One flag and nothing else, which is the point: `bootstrap` now seeds the rule catalogue as
    well, so this fixture sets up a store exactly the way the README tells a reader to. A test
    that had to seed something the documented command does not would be testing a private path.

    `LOUPE_API_URL` is set for the duration, so a `LoupeClient()` built with no arguments finds
    this server — which exercises `client.base_url()` as well, the indirection the UI relies on
    to be pointed at another host without a code change.
    """
    con = connect(store_path)
    app = create_app(con, bootstrap=True)
    try:
        for url in _serve(app):
            monkeypatch.setenv("LOUPE_API_URL", url)
            yield url
    finally:
        con.close()


@pytest.fixture
def api_client(live_api: str) -> Iterator[LoupeClient]:
    """The **real** `LoupeClient`, pointed at the live server.

    Not a stub and not `TestClient`: this is the object a Python caller gets from
    `loupe.client` in production, so a defect in how it builds a multipart body or reads a
    problem response shows up here and nowhere else in the suite.
    """
    yield LoupeClient()


@pytest.fixture
def upload_file(api_client: LoupeClient, fixture_path):
    """POST one fixture through the real client, over the wire, as a multipart upload."""

    def _upload(name: str, *, validate: bool = True) -> dict:
        path = fixture_path(name)
        return api_client.create_batch(path.name, path.read_bytes(), validate=validate)

    return _upload
