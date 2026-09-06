"""Canned envelopes and the stub client for the UI tier

Named `ui_helpers` rather than `helpers`: pytest puts each test directory on
`sys.path`, so a second top-level `helpers` would collide with
`tests/quality/helpers.py` and whichever imported first would win — passing in
isolation and failing in the full run. (`specs/loupe-solution-design.md` §13).

Pages are driven by `streamlit.testing.v1.AppTest` over a **stubbed client**, so these tests
assert view assembly and never reach DuckDB. That is the point of the tier: a page test that
needed a database would be re-testing `quality`, and a page test that needed a live server
could not run in CI at all.

The stub is the seam done-when 3 created. Because `ui.runtime.get_client()` is the single
place the pages resolve a client, one `use_client()` call puts a fake in front of every panel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loupe.ui.client import ApiProblem

APP = str(Path(__file__).resolve().parents[2] / "src" / "loupe" / "ui" / "app.py")


class FakeClient:
    """Answers the calls the pages make, from canned envelopes.

    Every response here is shaped like `specs/api-contract.md` says, because a stub that
    answered a shape the API does not produce would let a page pass while being broken.
    """

    def __init__(self, **overrides: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses: dict[str, Any] = {
            "health": HEALTH,
            "summary": SUMMARY,
            "metrics": {"data": TREND, "total": len(TREND), "dimension": "completeness"},
            "contracts": CONTRACTS,
            "findings": {"data": FINDINGS, "total": len(FINDINGS)},
            "changelog": {"data": CHANGELOG, "total": len(CHANGELOG), "run_id": "run-1"},
            "bars_daily": {"data": BARS},
            "vwap": {"data": VWAP},
            "compare": {"data": COMPARE},
            "insights_patterns": PATTERNS,
            "insights_suggestions": SUGGESTIONS,
        }
        self._responses.update(overrides)

    def _answer(self, name: str, **params: Any) -> Any:
        self.calls.append((name, params))
        value = self._responses.get(name)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(**params)
        return value if value is not None else {"data": []}

    def health(self, **p: Any):
        return self._answer("health", **p)

    def summary(self, **p: Any):
        return self._answer("summary", **p)

    def metrics(self, **p: Any):
        return self._answer("metrics", **p)

    def contracts(self, **p: Any):
        return self._answer("contracts", **p)

    def findings(self, **p: Any):
        return self._answer("findings", **p)

    def changelog(self, **p: Any):
        return self._answer("changelog", **p)

    def bars_daily(self, **p: Any):
        return self._answer("bars_daily", **p)

    def vwap(self, **p: Any):
        return self._answer("vwap", **p)

    def compare(self, **p: Any):
        return self._answer("compare", **p)

    def suggestions(self, **p: Any):
        """One key, because the real client has one route.

        `LoupeClient.suggestions` is `get("/insights/suggestions")`, so answering a separate
        `suggestions` key here would let a stub set up a world where the Address cell and the
        Suggestions panel disagree about the same request — which the API cannot produce.
        """
        return self.get("/insights/suggestions", **p)

    def preview(self, filename: str, content: bytes):
        return self._answer("preview", filename=filename)

    def create_batch(self, filename: str, content: bytes, **p: Any):
        return self._answer("create_batch", filename=filename)

    def get(self, path: str, **p: Any):
        return self._answer(path.strip("/").replace("/", "_"), **p)


#: A route the build does not carry. Kept after slice 6 shipped the insights routes, because
#: both sides of that branch still matter: a UI pointed at an older API must explain itself
#: rather than render an empty panel that reads as "nothing to report".
NOT_BUILT = ApiProblem(status=404, code=None, title="Not Found", detail="No such route")

#: `CAP.FREQUENCY_UNAVAILABLE`: a refusal that is *not* an empty series (§6, contract line 428).
VWAP_REFUSED = ApiProblem(
    status=422,
    code="CAP.FREQUENCY_UNAVAILABLE",
    title="Frequency unavailable",
    detail="ZCZ25 holds daily records only; a 15-minute VWAP needs minute bars.",
)

#: `GET /v1/health`. `synthetic_batches` is zero here: the default stub is a store holding only
#: real vendor data, which is what the app must look like before anyone presses Inject.
HEALTH: dict[str, Any] = {
    "status": "ok",
    "schema_applied": True,
    "rules_seeded": True,
    "records": 115622,
    "contracts": 2,
    "batches": 2,
    "synthetic_batches": 0,
    "synthetic_records": 0,
}

#: The same store after labelled defects were planted. Every surface reporting a number has to
#: say so while this is true, and has to keep saying so on every rerun
#: (`plans/07-demo-corpus.md` done-when 5).
SYNTHETIC_HEALTH: dict[str, Any] = {
    **HEALTH,
    "records": 115967,
    "batches": 3,
    "synthetic_batches": 1,
    "synthetic_records": 345,
}

#: A store nobody has loaded anything into — where the demo panel offers the fetch.
EMPTY_HEALTH: dict[str, Any] = {**HEALTH, "records": 0, "contracts": 0, "batches": 0}

CONTRACTS = {
    "data": [
        {"contract_id": "ZCZ25", "root": "ZC"},
        {"contract_id": "ESZ25", "root": "ES"},
    ],
    "total": 2,
}

SUMMARY: dict[str, Any] = {
    "scope": {"contracts": ["ZCZ25", "ESZ25"], "basis": "clean"},
    "overall_score": 68.5,
    "score_method": "weighted mean of in-scope dimension scores",
    "slices": [
        {
            "contract_id": "ZCZ25",
            "frequency": "daily",
            "overall": 41.0,
            "dimensions": {"completeness": {"score": 88.0}},
            "scope_signature": "cmp+val+con+unq+tim",
            "dimensions_not_in_scope": [
                {
                    "dimension": "reconciliation",
                    "reason": "only one frequency uploaded for this contract",
                }
            ],
        },
        {
            "contract_id": "ESZ25",
            "frequency": "minute",
            "overall": 96.0,
            "dimensions": {"completeness": {"score": 99.0}},
            "scope_signature": "cmp+val+con+unq+tim",
            "dimensions_not_in_scope": [
                {
                    "dimension": "reconciliation",
                    "reason": "only one frequency uploaded for this contract",
                }
            ],
        },
    ],
    "contracts": [
        {
            "contract_id": "ZCZ25",
            "score": 41.0,
            "status": "ATTN",
            "frequencies": ["daily"],
            "finding_count": 9,
            "top_issue": {
                "rule_id": "CON.CLOSE_OUT_OF_RANGE",
                "label": "Close outside the bar range",
                "severity": "error",
                "findings": 6,
            },
            "settlement_issue": {
                "rule_id": "CON.CLOSE_OUT_OF_RANGE",
                "label": "Close outside the bar range",
                "severity": "warning",
                "findings": 2,
            },
        },
        {
            "contract_id": "ESZ25",
            "score": 96.0,
            "status": "OK",
            "frequencies": ["minute"],
            "finding_count": 1,
            "top_issue": {
                "rule_id": "CMP.MISSING_TIMESTAMP",
                "label": "Missing timestamps",
                "severity": "warning",
                "findings": 1,
            },
            "settlement_issue": None,
        },
    ],
    "worst_field": {"field": "close", "findings": 6, "considered": 6, "total": 10},
    "records": {"total": 1000, "excluded": 12},
    "top_issues": [{"rule_id": "CON.CLOSE_OUT_OF_RANGE", "findings": 6, "severity": "error"}],
    "meta": {"run_id": "run-1"},
}

TREND = [
    {"day": "2025-12-10", "dimension_score": 98.0},
    {"day": "2025-12-11", "dimension_score": 92.0},
    {"day": "2025-12-12", "dimension_score": 71.0},
]

FINDINGS = [
    {
        "finding_id": "f1",
        "rule_id": "CON.CLOSE_OUT_OF_RANGE",
        "contract_id": "ZCZ25",
        "frequency": "daily",
        "trade_date": "2025-12-12",
        "severity": "error",
        "affected_rows": 1,
        "status": "open",
        "details": {"message": "close 412 > high 410"},
        "corroboration": {
            "state": "disputed",
            "reason": "The minute tape found prints above the stated high.",
            "detail": {"field": "high", "ticks": 3, "finding_ids": ["f9"]},
        },
    },
    {
        "finding_id": "f2",
        "rule_id": "CMP.MISSING_TIMESTAMP",
        "contract_id": "ZCZ25",
        "frequency": "minute",
        "trade_date": "2025-03-14",
        "severity": "warning",
        "affected_rows": 18,
        "status": "open",
        # No `corroboration` key at all — the fourth answer. A minute-grain completeness
        # finding is not a claim the daily file can speak to, and absence is how the API says
        # so (`specs/api-contract.md` §6.2).
        "details": {"message": "18 missing minute slots"},
    },
]

#: The same book with the tape agreeing, so the opposite reading can be asserted apart. Two
#: findings that render identically but instruct a reader to do opposite things is the failure
#: §8.7 exists to prevent, and a stub carrying only one state could not catch it.
CONFIRMED_FINDINGS: list[dict[str, Any]] = [
    {
        **FINDINGS[0],
        "corroboration": {
            "state": "confirmed",
            "reason": "Vendor high and low agree with the minute tape for this session.",
            "detail": {"minute_coverage_pct": 99.1},
        },
    },
    FINDINGS[1],
]

CHANGELOG = [
    {
        "contract_id": "ZCZ25",
        "trade_date": "2025-12-12",
        "frequency": "daily",
        "rule_id": "CON.CLOSE_OUT_OF_RANGE",
        "label": "Close outside the bar range",
        "action": "exclude",
        "records": 4,
    }
]

BARS = [
    {
        "contract_id": "ZCZ25",
        "trade_date": "2025-12-11",
        "open": 408.0,
        "high": 411.25,
        "low": 407.5,
        "close": 410.0,
        "volume": 18210,
        "max_severity": None,
    },
    {
        "contract_id": "ZCZ25",
        "trade_date": "2025-12-12",
        "open": 410.25,
        "high": 410.0,
        "low": 407.0,
        "close": 412.0,
        "volume": 20104,
        "max_severity": "error",
    },
]

VWAP = [{"ts_utc": "2025-12-12T15:00:00Z", "vwap": 410.5}]

COMPARE = [
    {"trade_date": "2025-12-11", "raw": 410.0, "clean": 410.0},
    {"trade_date": "2025-12-12", "raw": 412.0, "clean": 411.0},
]


#: The same book with both grains loaded: reconciliation is in scope, so nothing is disclosed.
RECONCILED: dict[str, Any] = {
    **SUMMARY,
    "slices": [
        {
            **slice_,
            "scope_signature": "cmp+val+con+unq+tim+rec",
            "dimensions_not_in_scope": [],
        }
        for slice_ in SUMMARY["slices"]
    ],
}


#: A mixed book: ZCZ25 is daily-only so reconciliation is out of scope for it, while ESZ25
#: holds both grains. The inventory then sorts a five-dimension score against a six-dimension
#: one in a single column, which is the comparison §11.3 says must not be made silently.
MIXED_SCOPE: dict[str, Any] = {
    **SUMMARY,
    "slices": [
        {
            **SUMMARY["slices"][0],
            "scope_signature": "cmp+val+con+unq+tim",
            "dimensions_not_in_scope": [
                {
                    "dimension": "reconciliation",
                    "reason": "only one frequency uploaded for this contract",
                }
            ],
        },
        {
            **SUMMARY["slices"][1],
            "scope_signature": "cmp+val+con+unq+tim+rec",
            "dimensions_not_in_scope": [],
        },
    ],
}


#: `GET /v1/insights/patterns`, copied from a real response rather than written to match the
#: page (`specs/loupe-solution-design.md` §13). `dimension` here is a *bucket* dimension —
#: where the findings concentrate — and not one of the six quality dimensions.
PATTERNS: dict[str, Any] = {
    "scope": {"contracts": ["ZCZ25"], "frequency_defaulted": False},
    "data": [
        {
            "pattern_id": "p_9f2c1a4b6d8e0f11",
            "rule_id": "CMP.MISSING_TIMESTAMP",
            "dimension": "hour_of_day",
            "bucket": "16:00-17:00 America/Chicago",
            "share_of_findings": 0.82,
            "share_of_records": 0.04,
            "lift": 20.5,
            "support": 412,
            "distinct_days": 61,
            "narrative": (
                "82% of missing timestamp findings fall in the 16:00-17:00 America/Chicago "
                "hour, across 61 sessions."
            ),
            "confidence": "high",
        }
    ],
    "total": 1,
    "meta": {"min_lift": 3.0, "min_support": 20, "min_periods": 3},
}

#: `GET /v1/insights/suggestions`. Note what is **not** here: no `actions`, no apply link and
#: no dismiss link. v1 identifies and suggests; it does not mutate (locked decision 10), and a
#: stub that invented an action key would let the report-only page tests pass against a payload
#: the API never sends.
SUGGESTIONS: dict[str, Any] = {
    "scope": {"contracts": ["ZCZ25"], "frequency_defaulted": False},
    "data": [
        {
            "suggestion_id": "s_31d7b0c95ea2f846",
            "from_pattern": "p_9f2c1a4b6d8e0f11",
            "kind": "calendar",
            "title": "Suppress the 16:00-17:00 CT maintenance break for ZC",
            "rationale": (
                "412 missing-timestamp findings across 61 sessions fall entirely within the "
                "CME daily maintenance break, when no trading occurs."
            ),
            "evidence": {"findings": 412, "sessions": 61, "lift": 20.5},
            "proposed_change": {
                "target": "ref.session_calendar",
                "operation": "add_halt_window",
                "params": {"root": "ZC", "start_local": "16:00:00", "end_local": "17:00:00"},
            },
            "expected_effect": {"findings_suppressed": 412, "completeness_delta_pct": 4.1},
            "confidence": 0.95,
        }
    ],
    "total": 1,
}
