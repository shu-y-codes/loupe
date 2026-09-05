"""Reference contract tests (`specs/api-contract.md` §3).

`GET /contracts` reports the range and the frequencies actually held so the UI can bound its
date pickers to real data and disable VWAP for a daily-only contract, rather than routing a
user into an error it could have predicted.
"""

from __future__ import annotations

MINUTE_FIXTURE = "insights_vwap_window.csv"
DAILY_FIXTURE = "con_derived_bar_invalid_vendor.csv"


def test_contracts_report_observed_coverage(client, upload):
    upload(MINUTE_FIXTURE)

    body = client.get("/v1/contracts").json()
    contract = next(c for c in body["data"] if c["contract_id"] == "ESZ25")

    assert contract["root"] == "ES"
    assert contract["frequencies_available"] == ["minute"]
    minute = contract["coverage"]["minute"]
    assert minute["records"] > 0 and minute["sessions"] > 0
    assert minute["first_trade_date"] <= minute["last_trade_date"]
    # The sample carries no expiry specification, so these are observed bounds.
    assert contract["dates_inferred"] is True
    assert contract["roll_date"] is None


def test_frequencies_available_lets_the_ui_disable_vwap(client, upload):
    """A daily-only contract advertises the fact, so the UI need not provoke the 422."""
    upload(DAILY_FIXTURE)

    contract = client.get("/v1/contracts/CLZ25").json()
    assert contract["frequencies_available"] == ["daily"]
    assert "minute" not in contract["coverage"]


def test_contracts_filter_by_frequency(client, upload):
    upload(MINUTE_FIXTURE)
    upload(DAILY_FIXTURE)

    minute = client.get("/v1/contracts", params={"frequency": "minute"}).json()
    daily = client.get("/v1/contracts", params={"frequency": "daily"}).json()

    assert [c["contract_id"] for c in minute["data"]] == ["ESZ25"]
    assert [c["contract_id"] for c in daily["data"]] == ["CLZ25"]


def test_contracts_filter_by_root(client, upload):
    upload(MINUTE_FIXTURE)
    body = client.get("/v1/contracts", params={"root": "ES"}).json()
    assert body["total"] >= 1
    assert all(c["root"] == "ES" for c in body["data"])


def test_unknown_contract_is_404(client):
    response = client.get("/v1/contracts/NOSUCH26")
    assert response.status_code == 404
    assert response.json()["code"] == "STR.UNKNOWN_CONTRACT"


def test_calendar_returns_sessions_for_loaded_data(client, upload):
    upload(MINUTE_FIXTURE)
    body = client.get("/v1/calendar", params={"root": "ES"}).json()
    assert body["total"] == len(body["data"])
    if body["data"]:
        day = body["data"][0]
        assert {"trade_date", "is_holiday", "is_early_close"} <= set(day)
