"""The `corroboration` object on a finding (`specs/api-contract.md` §6.2, done-when 8).

It rides on the finding rather than on a route of its own, so these tests read it off
`GET /v1/dq/findings` and `GET /v1/dq/findings/{id}` and assert the two agree. A route of its
own was the alternative and is worse: it would let a client render "close outside the range"
without the qualification that decides what the reader should do about it.

Four answers are asserted apart, over four inputs chosen to produce them, because an
implementation that returned one answer always would satisfy any test written about that one
answer (`specs/loupe-solution-design.md` §13).

Named for the envelope rather than for the module: pytest puts each test directory on
`sys.path`, so this file and `tests/quality/test_corroboration.py` cannot share a basename —
whichever imported first would win, passing alone and failing in the full run.
"""

from __future__ import annotations

import json

import pytest

from loupe.quality import assess

MINUTE = "rec_corroboration_minute.csv"
DAILY = "rec_corroboration_daily.csv"


@pytest.fixture
def corroborated(client, api_con, upload):
    """A book holding one dual-grain contract and one daily-only contract.

    The committed fixtures carry three bars against a 1,380-slot calendar grid, so the seeded
    0.98 coverage gate would suppress every comparison. It is lowered in the seeded row — the
    way a deployment would — and the gate itself is asserted from both sides in
    `tests/quality/test_corroboration.py`.
    """
    assert upload(MINUTE, validate=False).status_code in (200, 201)
    params = json.loads(
        api_con.execute(
            "SELECT CAST(params AS VARCHAR) FROM dq.dq_rule WHERE rule_id = 'REC.OHLC_DISAGREE'"
        ).fetchone()[0]
    )
    params["min_coverage_pct"] = 0.001
    api_con.execute(
        "UPDATE dq.dq_rule SET params = ? WHERE rule_id = 'REC.OHLC_DISAGREE'",
        [json.dumps(params, sort_keys=True)],
    )
    assert upload(DAILY, validate=False).status_code in (200, 201)
    assess(api_con, min_records=1)
    return client


def _findings(client, **params):
    response = client.get("/v1/dq/findings", params={"limit": 500, **params})
    assert response.status_code == 200
    return response.json()["data"]


def _one(client, rule_id, frequency, contract_id, trade_date):
    matches = [
        f
        for f in _findings(client, rule_id=rule_id)
        if f["frequency"] == frequency
        and f["contract_id"] == contract_id
        and f["trade_date"] == trade_date
    ]
    assert len(matches) == 1, f"fixture produced {len(matches)} {rule_id} {frequency} findings"
    return matches[0]


# ------------------------------------------------------------------------ the four answers


def test_a_confirmed_range_licenses_reading_the_finding_as_being_about_the_close(corroborated):
    finding = _one(
        corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-15"
    )
    assert finding["corroboration"]["state"] == "confirmed"
    assert finding["corroboration"]["reason"]
    assert finding["corroboration"]["detail"]["minute_coverage_pct"] is not None


def test_a_disputed_range_cites_the_findings_that_dispute_it(corroborated):
    finding = _one(
        corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-16"
    )
    corroboration = finding["corroboration"]
    assert corroboration["state"] == "disputed"
    assert corroboration["detail"]["field"] in ("high", "low")
    assert corroboration["detail"]["finding_ids"]

    # The cited findings must actually be retrievable, or the citation is decoration.
    cited = corroborated.get(f"/v1/dq/findings/{corroboration['detail']['finding_ids'][0]}")
    assert cited.status_code == 200
    assert cited.json()["rule_id"] == "REC.OHLC_DISAGREE"


def test_one_granularity_is_not_comparable(corroborated):
    finding = _one(
        corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESH26", "2025-09-15"
    )
    assert finding["corroboration"]["state"] == "not_comparable"
    assert "ESH26" in finding["corroboration"]["reason"]


def test_corroboration_is_absent_where_it_does_not_apply(corroborated):
    """Null is the fourth answer and means *not applicable* — a different fact from
    `not_comparable`, which means applicable and unevaluable."""
    finding = _one(
        corroborated, "CON.CLOSE_OUT_OF_RANGE", "minute", "ESZ25", "2025-09-15"
    )
    assert finding["corroboration"] is None


def test_the_four_answers_are_pairwise_distinct_on_the_wire(corroborated):
    """The guard: one answer returned always would pass three of the four tests above."""
    answers = [
        _one(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-15"),
        _one(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-16"),
        _one(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESH26", "2025-09-15"),
        _one(corroborated, "CON.CLOSE_OUT_OF_RANGE", "minute", "ESZ25", "2025-09-15"),
    ]
    states = [
        f["corroboration"]["state"] if f["corroboration"] else None for f in answers
    ]
    assert states == ["confirmed", "disputed", "not_comparable", None]
    assert len(set(states)) == 4


# ------------------------------------------------------------------ both routes carry it


def test_the_detail_route_carries_the_same_object_as_the_list(corroborated):
    """§6.2 names both. The detail view is where a reader looks hardest, so it is the one
    place the qualification must not be dropped."""
    listed = _one(corroborated, "CON.CLOSE_OUT_OF_RANGE", "daily", "ESZ25", "2025-09-16")
    detail = corroborated.get(f"/v1/dq/findings/{listed['finding_id']}").json()
    assert detail["corroboration"] == listed["corroboration"]


def test_it_is_computed_and_never_stored(api_con, corroborated):
    """No column on `dq.dq_finding`, no finding of its own, and no `COR.*` rule."""
    columns = {
        row[0]
        for row in api_con.execute("DESCRIBE dq.dq_finding").fetchall()
    }
    assert "corroboration" not in columns
    assert not api_con.execute(
        "SELECT count(*) FROM dq.dq_finding WHERE rule_id LIKE 'COR.%'"
    ).fetchone()[0]


# ------------------------------------------------- the callout it qualifies, asserted present


def test_a_corroborated_contract_still_carries_its_closing_day_callout(corroborated):
    """§11.6: reconciliation qualifies the callout, it does not replace or suppress it.

    Asserted **present** on a dual-grain contract rather than only absent elsewhere. Slice 5's
    settlement assertions all held on single-grain fixtures, so none of them could have caught
    a `REC.*` finding written on the wrong side of `frequency` — which is silently dropped by
    the daily-grain filter rather than raising anything.
    """
    from loupe.quality import SETTLEMENT_RULES

    body = corroborated.get("/v1/dq/summary", params={"contract": "ESZ25"}).json()
    (row,) = [c for c in body["contracts"] if c["contract_id"] == "ESZ25"]

    assert sorted(row["frequencies"]) == ["daily", "minute"], "must be the dual-grain contract"
    assert row["settlement_issue"] is not None, "the callout must survive reconciliation"
    assert row["settlement_issue"]["rule_id"] in SETTLEMENT_RULES


def test_no_rec_rule_reaches_the_closing_day_column(corroborated):
    """§11.6's reversal: `REC.CLOSE_CONVENTION` is `info` and fires on an *expected*
    difference, and the Closing-day column is what a risk manager reads as what is **wrong**
    with a settlement. Filling it with a non-error is noise in the one column that must have
    none."""
    from loupe.quality import SETTLEMENT_RULES

    assert not [r for r in SETTLEMENT_RULES if r.startswith("REC.")]
    body = corroborated.get("/v1/dq/summary").json()
    callouts = [c["settlement_issue"] for c in body["contracts"] if c["settlement_issue"]]
    assert callouts, "an empty column would make this assertion vacuous"
    assert not [c for c in callouts if c["rule_id"].startswith("REC.")]


def test_reconciliation_reaches_the_score_through_the_summary(corroborated):
    """The other half of done-when 6, on the wire: the dual-grain contract's slices carry the
    reconciliation dimension and the 1.20 denominator §11.3 requires."""
    body = corroborated.get("/v1/dq/summary", params={"contract": "ESZ25"}).json()
    slices = [s for s in body["slices"] if s["contract_id"] == "ESZ25"]
    assert slices
    for sliced in slices:
        assert "reconciliation" in sliced["dimensions_in_scope"]
        assert sliced["scope_signature"].endswith("+rec")
        assert sliced["weight_denominator"] == pytest.approx(1.20)
