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
            "health": {"status": "ok", "schema_applied": True, "rules_seeded": True},
            "summary": SUMMARY,
            "metrics": {"data": TREND, "total": len(TREND), "dimension": "completeness"},
            "contracts": CONTRACTS,
            "findings": {"data": FINDINGS, "total": len(FINDINGS)},
            "changelog": {"data": CHANGELOG, "total": len(CHANGELOG), "run_id": "run-1"},
            "bars_daily": {"data": BARS},
            "vwap": {"data": VWAP},
            "compare": {"data": COMPARE},
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
        return self._answer("suggestions", **p)

    def preview(self, filename: str, content: bytes):
        return self._answer("preview", filename=filename)

    def create_batch(self, filename: str, content: bytes, **p: Any):
        return self._answer("create_batch", filename=filename)

    def get(self, path: str, **p: Any):
        return self._answer(path.strip("/").replace("/", "_"), **p)


#: A route that does not exist yet — patterns and suggestions land in slice 6.
NOT_BUILT = ApiProblem(status=404, code=None, title="Not Found", detail="No such route")

#: `CAP.FREQUENCY_UNAVAILABLE`: a refusal that is *not* an empty series (§6, contract line 428).
VWAP_REFUSED = ApiProblem(
    status=422,
    code="CAP.FREQUENCY_UNAVAILABLE",
    title="Frequency unavailable",
    detail="ZCZ25 holds daily records only; a 15-minute VWAP needs minute bars.",
)

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
        },
        {
            "contract_id": "ESZ25",
            "frequency": "minute",
            "overall": 96.0,
            "dimensions": {"completeness": {"score": 99.0}},
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
    "worst_field": {"field": "close", "findings": 6},
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
        "details": {"message": "18 missing minute slots"},
    },
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
