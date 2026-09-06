"""OpenAPI is generated from the app, and the v1 boundary is visible in it.

The document is architecture evidence (`specs/api-contract.md` §2), so these tests assert
what a reader of the spec would check: that every v1 area is present, that no extension
route has quietly appeared, and that the descriptions carrying provenance survive.
"""

from __future__ import annotations

import pytest

V1_PATHS = {
    "/v1/health",
    "/v1/contracts",
    "/v1/contracts/{contract_id}",
    "/v1/calendar",
    "/v1/ingest/preview",
    "/v1/ingest/batches",
    "/v1/ingest/batches/{batch_id}",
    "/v1/ingest/batches/{batch_id}/rejects",
    "/v1/analytics/bars/daily",
    "/v1/analytics/vwap",
    "/v1/analytics/compare",
    "/v1/dq/summary",
    "/v1/dq/metrics",
    "/v1/dq/findings",
    "/v1/dq/findings/{finding_id}",
    # Slice 5 (plans/05-ui.md, done-when 1): the Trader and Analyst changelog panels had no
    # read path over `dq.cleaning_action`.
    "/v1/dq/changelog",
    "/v1/dq/rules",
    "/v1/dq/runs",
    "/v1/dq/runs/{run_id}",
}


@pytest.fixture
def spec(client):
    response = client.get("/v1/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_openapi_is_served_under_v1(spec):
    assert spec["info"]["title"] == "Loupe API"
    assert set(spec["paths"]) == V1_PATHS


def test_no_extension_routes_are_exposed(spec):
    """The v1 cut is enforced by absence, not by a route that exists and refuses."""
    for path in spec["paths"]:
        assert "/review" not in path
        assert "/apply" not in path
        assert "/dismiss" not in path
    # Catalogue mutation is an extension: rules are readable and nothing more.
    assert set(spec["paths"]["/v1/dq/rules"]) == {"get"}


def test_findings_are_read_only_in_the_document(spec):
    assert set(spec["paths"]["/v1/dq/findings"]) == {"get"}
    assert set(spec["paths"]["/v1/dq/findings/{finding_id}"]) == {"get"}


def test_insights_routes_are_absent_until_slice_6(spec):
    """Patterns and suggestions are v1 in the contract but built in slice 6."""
    assert not [p for p in spec["paths"] if p.startswith("/v1/insights")]


def test_trade_date_parameters_say_they_are_session_dates(spec):
    """Dates are trade dates, never calendar dates, and the document has to say so."""
    params = spec["paths"]["/v1/analytics/bars/daily"]["get"]["parameters"]
    start = next(p for p in params if p["name"] == "start")
    assert "trade date" in start["description"].lower()
    assert "never a calendar date" in start["description"]


def test_frequency_parameter_documents_the_default(spec):
    params = spec["paths"]["/v1/analytics/bars/daily"]["get"]["parameters"]
    frequency = next(p for p in params if p["name"] == "frequency")
    assert "finest granularity" in frequency["description"]
