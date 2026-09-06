"""The Summary inventory: rollup, callouts, status, trend and worst field.

`plans/05-ui.md` done-when 2. These assert the *decisions* the plan settled, not just the
envelope: that the rollup takes the worst frequency rather than a mean, that the closing-day
callout is settlement-filtered at daily grain, that status follows severity and never a score
threshold, and that the worst-field tile is derived from rule identity.
"""

from __future__ import annotations

DEFECT_FIXTURE = "con_close_out_of_range.csv"
MINUTE_FIXTURE = "insights_vwap_window.csv"
#: A vendor **daily** file whose close sits outside the bar range — the only fixture that
#: reaches the Closing-day column, and so the only one that can prove it is populated.
SETTLEMENT_FIXTURE = "con_derived_bar_invalid_vendor.csv"


def _summary(client):
    response = client.get("/v1/dq/summary")
    assert response.status_code == 200
    return response.json()


def test_summary_carries_one_row_per_contract_alongside_the_slices(client, upload):
    upload(DEFECT_FIXTURE)
    body = _summary(client)

    assert body["contracts"], "the inventory table has no rows to render"
    ids = [row["contract_id"] for row in body["contracts"]]
    assert len(ids) == len(set(ids)), "one row per contract, not per contract x frequency"
    assert set(ids) == {s["contract_id"] for s in body["slices"]}

    row = body["contracts"][0]
    assert {"score", "status", "frequencies", "finding_count", "top_issue"} <= set(row)


def test_a_contract_rolls_up_to_its_worst_frequency(client, upload):
    """Min across slices, not a mean: a clean minute tape must not bury a broken daily file."""
    upload(DEFECT_FIXTURE)
    body = _summary(client)

    for row in body["contracts"]:
        mine = [
            s["overall"]
            for s in body["slices"]
            if s["contract_id"] == row["contract_id"] and s["overall"] is not None
        ]
        if mine:
            assert row["score"] == min(mine)
        else:
            assert row["score"] is None


def test_a_single_frequency_contract_rolls_up_to_its_only_slice(client, upload):
    upload(DEFECT_FIXTURE)
    body = _summary(client)

    single = [row for row in body["contracts"] if len(row["frequencies"]) == 1]
    assert single, "fixture should hold at least one single-frequency contract"
    for row in single:
        only = next(
            s for s in body["slices"] if s["contract_id"] == row["contract_id"]
        )
        assert row["score"] == only["overall"]


def test_status_follows_severity_and_not_a_score_cut(client, upload):
    """`ATTN` iff an open error/critical finding exists — never a threshold on the score."""
    upload(DEFECT_FIXTURE)
    body = _summary(client)

    for row in body["contracts"]:
        findings = client.get(
            "/v1/dq/findings", params={"contract": row["contract_id"], "limit": 1000}
        ).json()["data"]
        severe = any(f["severity"] in ("error", "critical") for f in findings)
        assert row["status"] == ("ATTN" if severe else "OK")


def test_a_daily_settlement_defect_produces_a_closing_day_callout(client, upload):
    """The positive case, and the one that proves the column is populated at all.

    Without this, every other settlement assertion in this file passes vacuously: a feature
    that returned `None` unconditionally would satisfy "only draws from the named set" and
    "minute-only has no callout" both. `CLZ25` in this fixture is a vendor **daily** file
    whose close sits outside the bar range, which is exactly the Risk wireframe's first row.
    """
    from loupe.quality import SETTLEMENT_RULES

    upload(SETTLEMENT_FIXTURE)
    body = _summary(client)

    called_out = [row for row in body["contracts"] if row["settlement_issue"]]
    assert called_out, "a daily close-out-of-range must reach the Closing-day column"

    callout = called_out[0]["settlement_issue"]
    assert callout["rule_id"] in SETTLEMENT_RULES
    assert callout["label"], "the callout reads from dq_rule.name, not widget copy"
    assert "daily" in called_out[0]["frequencies"]


def test_the_settlement_callout_draws_only_from_the_named_set(client, upload):
    """Risk's Closing-day column, `SETTLEMENT_RULES` at daily grain (§11.6)."""
    from loupe.quality import SETTLEMENT_RULES

    upload(SETTLEMENT_FIXTURE)
    body = _summary(client)

    seen = 0
    for row in body["contracts"]:
        callout = row["settlement_issue"]
        if callout is not None:
            seen += 1
            assert callout["rule_id"] in SETTLEMENT_RULES
            assert callout["label"], "the callout reads from dq_rule.name, not widget copy"
    assert seen, "this assertion is only worth making against a populated column"


def test_a_minute_only_contract_has_no_closing_day_callout(client, upload):
    """The em dash is the intended reading: settlement lives in the daily file."""
    upload(MINUTE_FIXTURE)
    body = _summary(client)

    minute_only = [row for row in body["contracts"] if row["frequencies"] == ["minute"]]
    assert minute_only, "fixture should hold a minute-only contract"
    for row in minute_only:
        # The rule fired — `CON.CLOSE_OUT_OF_RANGE` is in the set — and the callout is still
        # empty, so it is the daily-grain clause doing the work and not an absent finding.
        assert row["settlement_issue"] is None
        assert row["finding_count"] > 0


def test_top_issue_is_per_contract_and_not_the_scope_wide_list(client, upload):
    upload(DEFECT_FIXTURE)
    body = _summary(client)

    assert any(row["top_issue"] for row in body["contracts"])

    for row in body["contracts"]:
        callout = row["top_issue"]
        if callout is None:
            assert row["finding_count"] == 0
            continue
        # The callout names a rule that fired *for this contract* — a scope-wide list
        # cannot make that claim, which is the whole reason the field exists.
        mine = client.get(
            "/v1/dq/findings", params={"contract": row["contract_id"], "limit": 1000}
        ).json()["data"]
        fired = {f["rule_id"] for f in mine}
        assert callout["rule_id"] in fired
        # And it is the most *serious* of them, not the most numerous.
        rank = {"critical": 4, "error": 3, "warning": 2, "info": 1}
        worst = max(rank.get(f["severity"], 0) for f in mine)
        assert rank.get(callout["severity"], 0) == worst


def test_worst_field_comes_from_rule_identity(client, upload):
    """§11.7: mapped rules only, and never a group-by over `details`."""
    from loupe.quality import RULE_SUBJECT_FIELD

    upload(DEFECT_FIXTURE)
    body = _summary(client)

    if body["worst_field"] is not None:
        assert body["worst_field"]["field"] in set(RULE_SUBJECT_FIELD.values())
        assert body["worst_field"]["findings"] > 0


def test_worst_field_is_absent_when_no_mapped_rule_fired(client, upload):
    """"Not applicable" is a real state, not a corner case: `OUT.*` and missing-slot runs
    are both unmapped by design."""
    from loupe.quality import RULE_SUBJECT_FIELD

    upload("out_return_mad.csv")
    body = _summary(client)

    findings = client.get("/v1/dq/findings", params={"limit": 1000}).json()["data"]
    if not any(f["rule_id"] in RULE_SUBJECT_FIELD for f in findings):
        assert body["worst_field"] is None


def test_metrics_can_isolate_one_dimension_for_the_settlement_trend(client, upload):
    """`group_by=day` averages the dimensions together; the trend needs one of them."""
    upload(DEFECT_FIXTURE)

    unfiltered = client.get("/v1/dq/metrics", params={"group_by": "day"}).json()
    assert unfiltered["dimension"] is None

    trend = client.get(
        "/v1/dq/metrics",
        params={"group_by": "day", "dimension": "completeness", "frequency": "daily"},
    )
    assert trend.status_code == 200
    body = trend.json()
    assert body["dimension"] == "completeness"
    assert body["total"] <= unfiltered["total"]
    for row in body["data"]:
        assert "day" in row and "dimension_score" in row


def test_an_unknown_dimension_is_refused_rather_than_silently_ignored(client):
    assert client.get(
        "/v1/dq/metrics", params={"group_by": "day", "dimension": "spelling"}
    ).status_code == 422
