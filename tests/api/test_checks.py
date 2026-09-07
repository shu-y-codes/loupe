"""`GET /v1/dq/checks` — the reviewer-strip envelope (`specs/api-contract.md` §6.6)."""

from __future__ import annotations

from datetime import date


def test_checks_requires_a_contract(client):
    response = client.get("/v1/dq/checks")
    assert response.status_code == 422


def test_unknown_family_is_400(client, upload):
    upload("con_close_out_of_range.csv")
    response = client.get("/v1/dq/checks", params={"contract": "ESZ25", "family": "outliers"})
    assert response.status_code == 400
    assert response.json()["code"] == "STR.INVALID_REQUEST"


def test_checks_returns_four_cards_and_overlay_marks(client, upload):
    upload("con_close_out_of_range.csv")
    response = client.get(
        "/v1/dq/checks", params={"contract": "ESZ25", "family": "invalid"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_id"] == "ESZ25"
    assert body["checked"] is True
    assert {card["label"] for card in body["families"]} == {
        "Gaps",
        "Duplicates",
        "Invalid values",
        "Recurring patterns",
    }
    invalid = next(card for card in body["families"] if card["family"] == "invalid")
    assert invalid["count"] >= 1
    assert any(row["invalid"] for row in body["overlay"]["ohlcv"])
    assert body["overlay"]["family"] == "invalid"
    assert "kind" in body["overlay"]["picture"]


def test_a_gap_overlay_marks_an_absent_session(client, upload):
    upload("cmp_session_missing.csv")
    body = client.get("/v1/dq/checks", params={"contract": "ESZ25", "family": "gaps"}).json()
    absent = [row for row in body["overlay"]["ohlcv"] if row["session"] == "absent"]
    assert absent
    assert date.fromisoformat(absent[0]["trade_date"]) == date(2025, 9, 16)


def test_outliers_do_not_increment_a_card(client, upload):
    upload("out_return_mad.csv")
    body = client.get("/v1/dq/checks", params={"contract": "ESZ25"}).json()
    assert not any("Outlying" in issue["what"] for issue in body["issues"])
    findings = client.get(
        "/v1/dq/findings", params={"rule_id": "OUT.RETURN_MAD", "contract": "ESZ25"}
    ).json()
    assert findings["total"] >= 1
