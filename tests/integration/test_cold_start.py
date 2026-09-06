"""Starting against a store nobody has set up.

This is the first thing a new user does and the one path no other tier covers: every fixture
elsewhere hands the app a connection that `apply_schema`, `seed_reference` and `seed_quality`
have already run over, so "empty database" has never been an input to a test.

Two properties matter, and they are different. The app must **degrade legibly** rather than
raise a raw DuckDB error at a user who has done nothing wrong; and `bootstrap=True` must
actually produce a working store, because that is what the README tells people to run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loupe.api import create_app
from loupe.data import connect


def test_a_brand_new_store_is_a_file_with_no_tables(cold_store, store_path: Path):
    """The starting condition, asserted so the tests below are known to begin from it."""
    assert store_path.exists(), "connect() creates the file"
    tables = cold_store.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema IN "
        "('ref', 'stage', 'dq', 'mart')"
    ).fetchone()[0]
    assert tables == 0


def test_health_reports_degraded_rather_than_raising(cold_store):
    """An unbootstrapped store answers, and says what is wrong with it.

    The alternative — a 500 with a DuckDB `Catalog Error` in it — tells a first-time user that
    the app is broken when the truth is that it has not been set up. `status` and
    `schema_applied` are what the UI reads to decide whether to invite a bootstrap or an
    upload, so the shape has to survive here rather than only on a healthy store.
    """
    from fastapi.testclient import TestClient

    with TestClient(create_app(cold_store)) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["schema_applied"] is False
    assert body["rules_seeded"] is False
    assert body["records"] == 0


@pytest.mark.parametrize(
    "path",
    ["/v1/contracts", "/v1/dq/summary", "/v1/insights/patterns", "/v1/analytics/bars/daily"],
)
def test_an_empty_store_refuses_legibly_rather_than_returning_a_500(cold_store, path):
    """Every route reachable before an upload must answer with a problem, not a stack trace.

    This tier found the defect: all four returned a bare 500 carrying a raw DuckDB
    `Catalog Error`, which tells a first-time user the app is broken when the truth is that it
    has not been set up. The `_catalog` handler in `api/app.py` now translates it.

    503 rather than a 4xx, because the request was fine and the server is not ready — and the
    underlying message is kept at the front of `detail` on purpose, so a genuinely missing
    relation on a healthy store still reads as what it is instead of being relabelled.
    """
    from fastapi.testclient import TestClient

    with TestClient(create_app(cold_store), raise_server_exceptions=False) as client:
        response = client.get(path)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "CAP.STORE_NOT_INITIALISED"
    assert "/v1/health" in body["detail"], "the refusal has to say how to find out more"
    assert "Traceback" not in response.text


def test_the_refusal_disappears_once_the_store_is_bootstrapped(store_path: Path):
    """The other side of the same branch: a set-up store answers these routes normally.

    Without this, `_catalog` could swallow every catalog error forever and the test above
    would still pass.
    """
    from fastapi.testclient import TestClient

    con = connect(store_path)
    try:
        with TestClient(create_app(con, bootstrap=True)) as client:
            for path in ("/v1/contracts", "/v1/dq/summary", "/v1/insights/patterns"):
                assert client.get(path).status_code == 200, path
    finally:
        con.close()


def test_bootstrap_produces_a_store_the_app_can_serve(store_path: Path):
    """The README's documented start: `create_app(..., bootstrap=True)` on an empty file.

    Asserted end to end rather than by checking that `apply_schema` was called — the question
    is whether the resulting store answers, not whether a function ran.
    """
    from fastapi.testclient import TestClient

    con = connect(store_path)
    try:
        with TestClient(create_app(con, bootstrap=True)) as client:
            body = client.get("/v1/health").json()
            assert body["status"] == "ok"
            assert body["schema_applied"] is True
            # One flag, a store that can actually be used. The rule catalogue used to be a
            # second step, which meant the documented start produced an app that answered
            # `/v1/health` cheerfully and refused every upload with `RulesNotSeeded`.
            assert body["rules_seeded"] is True
    finally:
        con.close()


def test_the_bootstrapped_schema_survives_reopening_the_file(store_path: Path):
    """Bootstrap has to write to the file, not to a connection.

    A `create_app(..., bootstrap=True)` whose tables lived only in the open handle would look
    perfectly healthy for one run and be empty on the next start — and nothing in the faster
    tiers could tell, because they are all `:memory:`.
    """
    con = connect(store_path)
    create_app(con, bootstrap=True)
    con.close()

    reopened = connect(store_path)
    try:
        assert reopened.execute("SELECT count(*) FROM dq.dq_rule").fetchone()[0] > 0
        assert reopened.execute("SELECT count(*) FROM ref.product").fetchone()[0] > 0
    finally:
        reopened.close()


def test_the_ui_can_reach_a_live_server_it_was_only_given_a_url_for(live_api, api_client):
    """The indirection the UI depends on, exercised rather than assumed.

    `LoupeClient()` takes no arguments here: it reads `LOUPE_API_URL`, which is the whole
    mechanism behind "pointing it at another host needs no code change". Every other UI test
    replaces the client entirely, so this line of the README has never been run by a test.
    """
    assert api_client.url == live_api
    assert api_client.health()["schema_applied"] is True
