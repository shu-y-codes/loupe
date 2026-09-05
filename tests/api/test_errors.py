"""RFC 7807 problem details, and the conventions §2 fixes for every endpoint.

One error renderer in the UI covers both transport families, which only works if every
refusal — FastAPI's own validation included — comes back in the same envelope with a `code`
from the same vocabulary as the findings.
"""

from __future__ import annotations

import pytest

from loupe.api import PROBLEM_MEDIA_TYPE

REQUIRED_MEMBERS = {"type", "title", "status", "detail", "instance", "code"}


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/analytics/bars/daily", {"basis": "cooked"}),
        ("/v1/analytics/bars/daily", {"frequency": "hourly"}),
        ("/v1/analytics/vwap", {"price_basis": "midpoint"}),
        ("/v1/dq/findings", {"severity": "catastrophic"}),
        ("/v1/dq/findings", {"limit": 5000}),
        ("/v1/dq/findings", {"offset": -1}),
        ("/v1/dq/metrics", {"group_by": "phase-of-moon"}),
        ("/v1/analytics/bars/daily", {"start": "not-a-date"}),
    ],
)
def test_validation_errors_are_problem_documents(client, path, params):
    response = client.get(path, params=params)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)

    body = response.json()
    assert set(body) >= REQUIRED_MEMBERS
    assert body["status"] == 422
    assert body["code"] == "STR.INVALID_REQUEST"
    assert body["detail"], "a problem must say what was wrong in words"
    assert body["instance"].startswith(path)


def test_the_offending_parameter_survives_into_meta(client):
    """`detail` reads as a sentence; `meta.errors` keeps the field a client would highlight."""
    body = client.get("/v1/dq/findings", params={"limit": 5000}).json()
    assert any("limit" in error["loc"] for error in body["meta"]["errors"])


def test_instance_carries_the_query_that_produced_the_problem(client, upload):
    upload("con_derived_bar_invalid_vendor.csv")
    body = client.get("/v1/analytics/vwap", params={"contract": "CLZ25"}).json()
    assert body["instance"] == "/v1/analytics/vwap?contract=CLZ25"


def test_error_codes_are_not_http_statuses(client, upload):
    """Two refusals can share a status and still need telling apart.

    `CAP.FREQUENCY_UNAVAILABLE` and a parameter validation failure are both 422; the `code`
    is what lets a client distinguish "your request was malformed" from "the data cannot
    answer that".
    """
    upload("con_derived_bar_invalid_vendor.csv")
    capability = client.get("/v1/analytics/vwap", params={"contract": "CLZ25"})
    malformed = client.get("/v1/analytics/vwap", params={"basis": "cooked"})

    assert capability.status_code == malformed.status_code == 422
    assert capability.json()["code"] == "CAP.FREQUENCY_UNAVAILABLE"
    assert malformed.json()["code"] == "STR.INVALID_REQUEST"


def test_a_404_is_a_problem_document_too(client):
    response = client.get("/v1/contracts/NOSUCH26")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert set(response.json()) >= REQUIRED_MEMBERS
