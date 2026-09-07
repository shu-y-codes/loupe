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
            "bars_daily": {
                "scope": {
                    "contracts": ["ZCZ25"],
                    "basis": "clean",
                    "frequency": "daily",
                    "frequency_defaulted": False,
                },
                "data": BARS,
                "meta": {"bar_source": "supplied_daily"},
            },
            "vwap": {"data": VWAP},
            "compare": {"data": COMPARE},
            "insights_patterns": PATTERNS,
            "insights_suggestions": SUGGESTIONS,
            "batches": BATCHES,
            "checks": checks_response,
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

    def checks(self, **p: Any):
        return self._answer("checks", **p)

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

    def batches(self, **p: Any):
        return self._answer("batches", **p)

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


def _batch(
    *,
    filename: str,
    file_format: str,
    origin: str,
    batch_id: str,
    frequency: str = "minute",
    contracts_detected: list[str] | None = None,
) -> dict[str, Any]:
    """A `BatchSummary`-shaped row. Keys are a subset of the model; see the stub-parity guard."""
    return {
        "batch_id": batch_id,
        "status": "succeeded",
        "filename": filename,
        "file_format": file_format,
        "origin": origin,
        "file_hash": "0" * 64,
        "frequency": frequency,
        "source_timezone": "America/Chicago",
        "ts_convention": "interval_start",
        "session_boundary": "17:00 America/Chicago",
        "rows_read": 100,
        "rows_accepted": 100,
        "rows_rejected": 0,
        "contracts_detected": contracts_detected if contracts_detected is not None else ["ESZ25"],
        "sessions_detected": 10,
        "trade_date_range": ["2024-01-18", "2025-12-19"],
        "dq_run_id": "run-1",
        "elapsed_ms": 100,
    }


#: `GET /v1/ingest/batches` after a demo load. One Parquet, one converted CSV (`origin=demo`).
BATCHES: dict[str, Any] = {
    "data": [
        _batch(
            filename="ESZ25.parquet",
            file_format="parquet",
            origin="demo",
            batch_id="b-parq",
        ),
        _batch(
            filename="SR3G26.csv",
            file_format="csv",
            origin="demo",
            batch_id="b-csv",
        ),
    ],
    "total": 2,
}

#: Same store after labelled defects were planted. The injected copy is also a CSV; that
#: mark is the synthetic disclosure, not the conversion mark.
SYNTHETIC_BATCHES: dict[str, Any] = {
    "data": [
        *BATCHES["data"],
        _batch(
            filename="SR3G26.injected.csv",
            file_format="csv",
            origin="injected",
            batch_id="b-inj",
        ),
    ],
    "total": 3,
}

EMPTY_BATCHES: dict[str, Any] = {"data": [], "total": 0}

#: Mixed grains so the ingested-file expander can name all three coverage groups.
MIXED_COVERAGE_CONTRACTS: dict[str, Any] = {
    "data": [
        {"contract_id": "ESZ25", "root": "ES", "frequencies_available": ["daily", "minute"]},
        {"contract_id": "ZCZ25", "root": "ZC", "frequencies_available": ["daily"]},
        {"contract_id": "SR3G26", "root": "SR3", "frequencies_available": ["minute"]},
    ],
    "total": 3,
}

MIXED_COVERAGE_BATCHES: dict[str, Any] = {
    "data": [
        _batch(
            filename="ESZ25.parquet",
            file_format="parquet",
            origin="demo",
            batch_id="b-esz-m",
            frequency="minute",
            contracts_detected=["ESZ25"],
        ),
        _batch(
            filename="ESZ25.csv",
            file_format="csv",
            origin="demo",
            batch_id="b-esz-d",
            frequency="daily",
            contracts_detected=["ESZ25"],
        ),
        _batch(
            filename="ZCZ25.parquet",
            file_format="parquet",
            origin="demo",
            batch_id="b-zcz",
            frequency="daily",
            contracts_detected=["ZCZ25"],
        ),
        _batch(
            filename="SR3G26.csv",
            file_format="csv",
            origin="demo",
            batch_id="b-sr3",
            frequency="minute",
            contracts_detected=["SR3G26"],
        ),
    ],
    "total": 4,
}

PLANTED_MANIFEST: dict[str, Any] = {
    "source": "data/samples/SR3G26.csv",
    "output": "data/demo/SR3G26.injected.csv",
    "rows_in": 345,
    "rows_out": 348,
    "seed": 20260906,
    "defects": [
        {
            "defect_id": "d-gap",
            "rule_id": "CMP.MISSING_TIMESTAMP",
            "kind": "delete_run",
            "contract_id": "SR3G26",
            "source_row": 12,
            "original": None,
            "injected": None,
        },
        {
            "defect_id": "d-dup",
            "rule_id": "UNQ.EXACT_DUPLICATE",
            "kind": "duplicate_row",
            "contract_id": "SR3G26",
            "source_row": 40,
            "original": None,
            "injected": None,
        },
        {
            "defect_id": "d-val",
            "rule_id": "VAL.NEGATIVE_VOLUME",
            "kind": "negate_volume",
            "contract_id": "SR3G26",
            "source_row": 88,
            "original": "100",
            "injected": "-100",
        },
        {
            "defect_id": "d-tim",
            "rule_id": "TIM.OUT_OF_ORDER",
            "kind": "swap_timestamps",
            "contract_id": "SR3G26",
            "source_row": 120,
            "original": None,
            "injected": None,
        },
    ],
}

CONTRACTS = {
    "data": [
        {
            "contract_id": "ZCZ25",
            "root": "ZC",
            "frequencies_available": ["daily"],
        },
        {
            "contract_id": "ESZ25",
            "root": "ES",
            "frequencies_available": ["minute"],
        },
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
    {
        "contract_id": "ZCZ25",
        "trade_date": "2025-12-11",
        "raw": {"open": 408.0, "high": 411.25, "low": 407.5, "close": 410.0, "volume": 18210},
        "clean": {"open": 408.0, "high": 411.25, "low": 407.5, "close": 410.0, "volume": 18210},
        "differs": False,
    },
    {
        "contract_id": "ZCZ25",
        "trade_date": "2025-12-12",
        "raw": {"open": 410.25, "high": 410.0, "low": 407.0, "close": 412.0, "volume": 20104},
        "clean": {"open": 410.25, "high": 410.0, "low": 407.0, "close": 411.0, "volume": 20104},
        "differs": True,
    },
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


#: Overlay marks for the stubbed contract. All family flags sit on the same rows so a test
#: that switches Gaps vs Invalid can see the join change which marks are drawn.
OHLCV_MARKS: list[dict[str, Any]] = [
    {
        "trade_date": "2025-12-11",
        "session": "present",
        "partial_gap": True,
        "duplicate": False,
        "invalid": False,
        "invalid_volume": False,
        "pattern_member": True,
        "caption": "18 missing slots at session open",
    },
    {
        "trade_date": "2025-12-12",
        "session": "present",
        "partial_gap": False,
        "duplicate": False,
        "invalid": True,
        "invalid_volume": False,
        "pattern_member": False,
        "caption": "Close outside the bar range",
    },
    {
        "trade_date": "2025-09-16",
        "session": "absent",
        "partial_gap": False,
        "duplicate": False,
        "invalid": False,
        "invalid_volume": False,
        "pattern_member": False,
        "caption": "Settlement never arrived",
    },
]

_PICTURES: dict[str, dict[str, Any]] = {
    "gaps": {
        "kind": "gaps_ribbon",
        "trade_date": "2025-12-11",
        "caption": "18 consecutive minute slots missing on 2025-12-11.",
        "rule_ids": ["CMP.MISSING_TIMESTAMP"],
        "slots": [
            {"label": "17:00", "present": False},
            {"label": "17:01", "present": False},
            {"label": "17:02", "present": True},
        ],
    },
    "duplicates": {
        "kind": "empty",
        "trade_date": None,
        "caption": "This check ran. Nothing in this window.",
        "rule_ids": [],
    },
    "invalid": {
        "kind": "invalid_cell",
        "trade_date": "2025-12-12",
        "caption": "Close outside the bar range",
        "rule_ids": ["CON.CLOSE_OUT_OF_RANGE"],
        "field": "close",
        "evidence_frequency": "daily",
        "evidence_source": "vendor",
        "bar": {
            "trade_date": "2025-12-12",
            "open": 410.25,
            "high": 410.0,
            "low": 407.0,
            "close": 412.0,
            "volume": 20104,
        },
    },
    "patterns": {
        "kind": "pattern_histogram",
        "trade_date": None,
        "caption": PATTERNS["data"][0]["narrative"],
        "rule_ids": [PATTERNS["data"][0]["rule_id"]],
        "rule_id": PATTERNS["data"][0]["rule_id"],
        "dimension": "hour_of_day",
        "axis_label": "Hour of day, exchange local",
        "patterns_total": 1,
        "buckets_shown": 1,
        "buckets": [
            {
                "label": PATTERNS["data"][0]["bucket"],
                "share_of_findings": PATTERNS["data"][0]["share_of_findings"],
                "share_of_records": PATTERNS["data"][0]["share_of_records"],
                "lift": PATTERNS["data"][0]["lift"],
                "support": PATTERNS["data"][0]["support"],
                "distinct_days": PATTERNS["data"][0]["distinct_days"],
            }
        ],
    },
}

CHECKS: dict[str, Any] = {
    "scope": {
        "contracts": ["ZCZ25"],
        "basis": "clean",
        "frequency": "daily",
        "frequency_defaulted": False,
    },
    "contract_id": "ZCZ25",
    "score": 41.0,
    "scope_signature": "cmp+val+con+unq+tim",
    "dimensions_not_in_scope": [
        {
            "dimension": "reconciliation",
            "reason": "only one frequency uploaded for this contract",
        }
    ],
    "frequencies": ["daily"],
    "checked": True,
    "families": [
        {
            "family": "gaps",
            "label": "Gaps",
            "count": 2,
            "unit": "runs",
            "detail": "1 session-open hole · 1 session absent",
        },
        {
            "family": "duplicates",
            "label": "Duplicates",
            "count": 0,
            "unit": "records",
            "detail": "0 exact copies · 0 key conflicts",
        },
        {
            "family": "invalid",
            "label": "Invalid values",
            "count": 1,
            "unit": "rows",
            "detail": "1 price · 0 volumes",
        },
        {
            "family": "patterns",
            "label": "Recurring patterns",
            "count": 1,
            "unit": "standing",
            "detail": "Open-hour gaps, 61 of 63 sessions",
        },
    ],
    "issues": [
        {
            "family": "gaps",
            "what": "Missing grid slots",
            "days": 1,
            "records": 18,
            "what_we_did": "Flagged; not auto-dropped",
        },
        {
            "family": "invalid",
            "what": "Close outside the bar range",
            "days": 1,
            "records": 1,
            "what_we_did": "excluded 4 records",
        },
        {
            "family": "patterns",
            "what": PATTERNS["data"][0]["narrative"],
            "days": 61,
            "records": 412,
            "what_we_did": "Reported; not applied",
        },
    ],
    "overlay": {
        "family": "gaps",
        "ohlcv": OHLCV_MARKS,
        "vwap": {
            "pattern_hours": ["16:00-17:00 America/Chicago"],
            "name_breaks": True,
        },
        "picture": _PICTURES["gaps"],
    },
    "meta": {"run_id": "run-1"},
}


def checks_response(**params: Any) -> dict[str, Any]:
    """Family-aware `/dq/checks` stub. Overlay flags are shared; picture follows `family`."""
    family = params.get("family") or "gaps"
    picture = _PICTURES.get(family) or _PICTURES["duplicates"]
    return {
        **CHECKS,
        "contract_id": params.get("contract") or "ZCZ25",
        "scope": {
            **CHECKS["scope"],
            "contracts": [params.get("contract") or "ZCZ25"],
            "frequency": params.get("frequency") or "daily",
            "frequency_defaulted": "frequency" not in params,
        },
        "issues": [row for row in CHECKS["issues"] if row["family"] == family],
        "overlay": {
            "family": family,
            "ohlcv": OHLCV_MARKS,
            "vwap": {
                "pattern_hours": ["16:00-17:00 America/Chicago"],
                "name_breaks": family in {"gaps", "patterns", "invalid"},
            },
            "picture": picture,
        },
    }
