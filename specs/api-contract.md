# Loupe — API contract

**Normative.** HTTP resources, conventions, request/response shapes, and error vocabulary
for FastAPI `/v1`. Promoted from research `_notes/cursor/05-api-contract.md` (now
archaeology). Summary and v1 boundary: `specs/loupe-solution-design.md` §11.
Handlers call `quality` / `insights` / `data`; this spec owns envelopes, not business maths.
Analytics semantics: `specs/analytics-semantics.md`. Rule IDs and score fields:
`specs/dq-rules-and-scoring.md`. Storage: `specs/data-model.md`. Sample numbers cited in
examples are owned by `specs/sample-corpus.md`.

Revised 2026-09-06: promoted from research; first normative version. Same day: v1 vs
extension boundaries for finding override, suggestion apply/dismiss, and catalogue
mutation routes are stated here to match solution brief §11 / §14 (the research note
listed those routes without the v1 cut).

**Scope of authority.** This spec owns *paths, query parameters, status codes, JSON
envelopes, and transport error codes (`STR.*`, `CAP.*`)*. It does not own DDL, rule
triggers, bar/VWAP formulae, or UI chrome. A number in an example payload is a citation
of the sample corpus unless it is a structural default (`limit` 100, max 1000).

**Build sequence.** Slices 4 and 6 implement this contract; §7's two routes land with the
reports they call. Handlers must not re-derive aggregations or scores; they call the
layers those sibling specs already define.

### v1 vs extension (routes)

| Area | v1 | Extension |
|---|---|---|
| Reference | `GET /health`, `/contracts`, `/calendar` | — |
| Ingest | preview, batches (201 / `file_hash` 409), list, detail, rejects, soft-delete purge | Async job table + 202 (only if ingest exceeds ~30s) |
| Analytics | bars/daily, vwap, compare | — |
| DQ | summary, metrics, findings **GET** (read-only), changelog **GET** (read-only), rules **GET**, runs POST/GET | `POST .../findings/{id}/review`; `POST` / `PATCH` `/dq/rules` |
| Insights | patterns **GET**, suggestions **GET** | `POST .../suggestions/{id}/apply`, `.../dismiss` |
| Auth | none | Router-level RBAC; no signature changes |

---

## 1. Design drivers

Three changes from the founding API draft drive this shape.

**Resources, not verbs.** One endpoint per metric (`/api/metric/count_duplicates`, …)
scales against the rule catalogue. `/dq/metrics` returning all dimensions scales with it.

**Coverage.** Daily bars, VWAP, contracts, patterns, suggestions, batch purge, and
(as extension) finding override are committed journeys; the founding draft omitted them.

**Granularity.** Every contract in the development sample exists at `minute` and/or
`daily`. Without `frequency`, `GET /v1/analytics/bars/daily` is ambiguous between
"aggregate the minute tape" and "return the supplied daily bars". The parameter, its
default, and the response echo are specified below and threaded through every endpoint
that touches records.

---

## 2. Conventions

- Base path `/v1`. Version from day one.
- All timestamps ISO 8601 with offset; **UTC on the wire**. The UI localises for display.
- `basis=clean|raw` on every analytic endpoint, default `clean`.
- `frequency=minute|daily` on every ingest, analytic, and data-quality endpoint. Exactly
  those two lowercase values, matching `files.csv` and `stage.market_record.frequency`.
- Dates are **trade dates** (session dates), never calendar dates. State this in the
  OpenAPI description of every date parameter.
- Pagination via `limit` (default 100, max 1000) and `offset`, with `total` in the response.
- Every endpoint is **synchronous**. Writes return the finished result, never a poll handle.
- Errors follow **RFC 7807** problem details.
- FastAPI generates OpenAPI at `/v1/openapi.json` — architecture evidence; keep Pydantic
  models well described.

### 2.1 Frequency, default, and echo

`frequency` selects the record grain a request **reads from**, not the grain it returns.
`GET /v1/analytics/bars/daily?frequency=minute` aggregates the minute tape into daily bars;
`frequency=daily` returns the supplied daily bars unchanged. Both return daily bars and are
not the same numbers — on `ESZ25` for trade date 2025-11-20 the derived close is 6552.00
against a supplied 6557.50 (settlement). See `specs/sample-corpus.md`.

**Default: the finest granularity held for the contracts in scope.** Minute when minute
records exist, daily otherwise. A fixed `daily` default would silently downgrade a
minute upload; requiring the parameter on every call blocks the simplest request.

**Every analytic and data-quality response echoes what served it.** The `scope` block
carries `frequency`, and `frequency_defaulted: true` when the client omitted it.
Defaulting is only safe because it is disclosed.

Requesting a frequency the contract does not hold is an **error**, not an empty result.
See §5 `GET /v1/analytics/vwap`.

### 2.2 Error shape

```json
{
  "type": "/errors/unsupported-file-format",
  "title": "Unsupported file format",
  "status": 415,
  "detail": "Received .xlsx; expected .csv or .parquet.",
  "instance": "/v1/ingest/batches",
  "code": "STR.UNSUPPORTED_FORMAT"
}
```

`code` ties API errors to the same vocabulary as findings. Two transport families are
reserved and are not DQ rule identifiers:

| Prefix | Meaning |
|---|---|
| `STR.*` | Request the loader cannot structurally accept |
| `CAP.*` | Well-formed request the ingested data cannot support |

One error renderer in the UI covers both.

---

## 3. Reference

```
GET /v1/health
GET /v1/contracts?root=&active_on=&frequency=
GET /v1/contracts/{contract_id}
GET /v1/calendar?root=&start=&end=
```

`GET /v1/contracts` powers every contract filter and returns the data range actually held
so date pickers bound to real data. It reports which frequencies the contract holds so the
UI can disable VWAP for a daily-only contract instead of routing to an error:

```json
{
  "data": [
    {
      "contract_id": "ESZ25", "root": "ES", "exchange": "CME",
      "contract_month": "2025-12",
      "tick_size": 0.25, "multiplier": 50.0,
      "coverage": {
        "minute": {"first_trade_date": "2024-01-18", "last_trade_date": "2025-12-19",
                   "sessions": 224, "records": 114477},
        "daily":  {"first_trade_date": "2021-06-04", "last_trade_date": "2025-12-19",
                   "sessions": 1145, "records": 1145}
      },
      "frequencies_available": ["minute", "daily"],
      "roll_date": null,
      "dates_inferred": true,
      "dq_score": 96.4
    }
  ],
  "total": 1
}
```

OpenAPI descriptions must state provenance for:

| Field | Provenance |
|---|---|
| `contract_month` | Parsed from the symbol and validated against the file manifest. `SR3M26` proves the root is not always two characters |
| `tick_size`, `multiplier` | Tick measured as the largest increment every observed price lies on; multiplier is seeded per root |
| `first_trade_date`, `last_trade_date`, `roll_date` | Observed data bounds, **not** listing or expiry dates |

`dates_inferred` is `true` for every contract loaded from the development sample, and
`roll_date` is `null`: the sample carries no expiry specification. The fields mean "we
observed data between these dates", never "the contract was listed between these dates".
When real expiry reference data is supplied, `dates_inferred` flips to `false` and
`roll_date` populates; the shape does not change.

---

## 4. Ingestion

```
POST   /v1/ingest/preview             dry run: columns, inferred tz, frequency, interval,
                                      session boundary, and what the upload enables
POST   /v1/ingest/batches             multipart upload → 201, synchronous
GET    /v1/ingest/batches?frequency=  list
GET    /v1/ingest/batches/{id}        status and counts
GET    /v1/ingest/batches/{id}/rejects paginated rejected rows
DELETE /v1/ingest/batches/{id}        purge this batch and its derived rows
```

### 4.1 Both granularities accepted

**Loupe accepts `minute` and `daily` uploads alike, and rejects an upload only on file
format** (CSV or Parquet). A granularity gate would invent a rejection the brief does not
ask for. Daily is required material: the development sample's natural defects live in the
daily files; the risk-manager persona works on settlements; reconciliation needs both.

Capability follows from what was supplied and is disclosed:

| Uploaded | Daily bars | Rolling 15-minute VWAP | Reconciliation |
|---|---|---|---|
| Minute only | Derived from the minute tape | Available | Not available |
| Daily only | Returned as supplied | **Not available** | Not available |
| Both | Derived, and compared against supplied | Available | Available |

A rolling 15-*day* VWAP from daily bars is **explicitly rejected** as a substitute for the
missing 15-minute figure. A daily-only upload gets a stated absence, not a lookalike.

### 4.2 Preview — capability disclosure

`POST /v1/ingest/preview` answers acceptance before anything is written; confirms timezone,
interval, and session-boundary inferences; and states what the upload will and will not
enable. Example — sample `ESZ25` minute file:

```json
{
  "filename": "ESZ25.parquet",
  "file_format": "parquet",
  "file_bytes": 2665396,
  "rows_total": 114477,
  "rows_sampled": 5000,
  "detected_columns": ["root_id","exchange","root","contract_symbol","timestamp_ms",
                       "timestamp_chicago_wall","trading_date","minute_of_day",
                       "open","high","low","close","volume"],
  "column_mapping": {
    "contract_symbol": "contract_id",
    "timestamp_chicago_wall": ["ts_exchange", "ts_utc"],
    "timestamp_ms": "ts_source_label",
    "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"
  },
  "unmapped_columns": ["root_id","exchange","root","trading_date","minute_of_day"],
  "missing_required": [],
  "inferred_frequency": {"value": "minute", "confidence": 1.0,
                         "method": "modal delta 60 s; 100% of 114476 deltas are exact multiples of it"},
  "inferred_timezone": {"value": "America/Chicago", "confidence": 0.99,
                        "method": "declared in package schema.json, confirmed by maintenance-break histogram"},
  "inferred_interval": {"value": "1 minute", "modal_share": 0.915,
                        "all_deltas_multiple_of_mode": true},
  "ts_convention": "interval_start",
  "session_boundary": {"value": "17:00 America/Chicago", "root": "ES",
                       "method": "seeded per root, cross-checked against observed dead zone 16:00-16:59"},
  "contracts_detected": ["ESZ25"],
  "estimated_rejects": 0,
  "verdict": "accept",
  "enables": {
    "daily_bars": {"available": true, "source": "derived"},
    "vwap_15m": {"available": true},
    "reconciliation": {"available": false,
                       "reason": "No daily records held for ESZ25. Upload the daily file to compare supplied and derived bars."}
  },
  "warnings": [
    "trading_date is a Chicago calendar date, not a session date, and will not be used as the trade date."
  ]
}
```

Load-bearing fields:

- `column_mapping` is not a bijection: one source column can map to a derived pair
  (`ts_utc` obtained by attaching `America/Chicago` to the wall-clock label).
- `inferred_interval` reports modal share as a diagnostic and gates on the
  multiple-of-mode test — modal share on this corpus runs as low as ~0.678 for a correct
  one-minute grid.
- `session_boundary` is an ingestion decision that can go wrong silently.
- `enables` is the point of the step: daily-only upload sees VWAP unavailable before commit.

Daily-only preview (`GCJ26`):

```json
{
  "filename": "GCJ26.parquet",
  "file_format": "parquet",
  "rows_total": 480,
  "detected_columns": ["root_id","exchange","root","contract_symbol","timestamp_ms",
                       "date","open","high","low","close","volume","open_interest"],
  "inferred_frequency": {"value": "daily", "confidence": 1.0,
                         "method": "one row per date; no time-of-day component"},
  "ts_convention": "session_date",
  "contracts_detected": ["GCJ26"],
  "verdict": "accept",
  "enables": {
    "daily_bars": {"available": true, "source": "supplied"},
    "vwap_15m": {"available": false,
                 "reason": "A 15-minute VWAP requires intraday records. This file has one row per session, so no intraday window exists to weight.",
                 "substitute_offered": false},
    "reconciliation": {"available": false,
                       "reason": "No minute records held for GCJ26. Upload the minute file to compare supplied and derived bars."}
  },
  "warnings": [
    "close is a settlement price, not a last trade, and may fall outside [low, high] on sessions with no trading."
  ]
}
```

`substitute_offered: false` is machine-readable: nothing has been quietly swapped in.

### 4.3 Batches

`POST /v1/ingest/batches` blocks until load and validation finish, then returns **201** with
the completed batch summary, or **409 with the existing batch** when `file_hash` already
exists — idempotent re-upload, surfaced rather than silently duplicated. The batch persists
`frequency`, timezone, timestamp convention, and session boundary — the four decisions a
later reprocessing must reproduce:

```json
{ "batch_id": "01H...", "status": "succeeded",
  "filename": "ESZ25.parquet", "file_format": "parquet",
  "file_hash": "73adf677d04da16fa297d556d63f9551f2e19b1481c54fa923c74a483b2b2866",
  "frequency": "minute",
  "source_timezone": "America/Chicago", "ts_convention": "interval_start",
  "session_boundary": "17:00 America/Chicago",
  "rows_read": 114477, "rows_accepted": 114477, "rows_rejected": 0,
  "contracts_detected": ["ESZ25"], "sessions_detected": 224,
  "trade_date_range": ["2024-01-18", "2025-12-19"],
  "dq_run_id": "01H...", "elapsed_ms": 6120 }
```

Uploads are the only way records enter the store. The UI "Load demo data" path posts files
already on local disk to this same endpoint; no request path fetches a third-party dataset.

`DELETE` implements purge: cascade to `stage.market_record`, `stage.record_reject`, the
batch's findings and the `mart.bar_daily` rows derived from them; soft delete
(`status = 'purged'`) so ingest history stays intact.

**"The batch's findings" is narrower than "every finding touching those sessions", and
deliberately so.** A purge removes findings it can *attribute* to the batch — those from a run
scoped to it (`dq.dq_run.batch_id`) and those pinned to one of its records. Findings written
by a **corpus-wide** run that are about a *session* rather than a record survive: that session
may hold another batch's records, and the finding is a statement about all of them. Guessing
which half of such a statement to delete would be worse than leaving it. The honest response
to a changed corpus is to re-validate it (`POST /v1/dq/runs`), which the response therefore
invites rather than performing implicitly.

### 4.4 Why synchronous; async as extension

Streamlit re-runs on every interaction and has no server push. Async ingest would need a
job table, client polling, and a rerun trigger — unjustified under single-user, local
DuckDB, sample-scale assumptions. Blocking is simpler and honest about completion.

**Extension:** job table, **202** with a job handle, UI polling. Trigger when sustained
ingest exceeds ~30s; enforce a hard upload size cap meanwhile.

---

## 5. Analytics

```
GET /v1/analytics/bars/daily?contract=&start=&end=&basis=&frequency=
GET /v1/analytics/vwap?contract=&start=&end=&basis=&frequency=minute&window=15m&price_basis=typical
GET /v1/analytics/compare?contract=&start=&end=&metric=vwap|close|ohlcv&compare=basis|frequency
```

### 5.1 Daily bars

`bars/daily` returns each bar with quality annotation attached. `contract` accepts a
comma-separated list. Scope travels in a `scope` block; each row names its own contract.
Example values are real sample citations (`ESZ25` 2025-11-20 complete session;
`ZCH26` 2026-01-13 incomplete):

```json
{
  "scope": {"contracts": ["ESZ25", "ZCH26"], "start": "2025-11-20", "end": "2026-01-13",
            "basis": "clean", "frequency": "minute", "frequency_defaulted": true},
  "data": [
    {
      "contract_id": "ESZ25", "root": "ES", "trade_date": "2025-11-20",
      "open": 6697.50, "high": 6791.25, "low": 6550.50, "close": 6552.00,
      "volume": 2883479,
      "record_count": 1380, "expected_count": 1380, "completeness_pct": 100.0,
      "finding_count": 0, "max_severity": null,
      "reconciliation": {
        "status": "compared", "ohl_agree": true,
        "supplied_close": 6557.50, "close_diff": -5.50,
        "supplied_volume": 2987357, "volume_ratio": 0.9652,
        "finding_ids": ["01H..."]
      }
    },
    {
      "contract_id": "ZCH26", "root": "ZC", "trade_date": "2026-01-13",
      "open": 421.75, "high": 422.75, "low": 417.25, "close": 420.25,
      "volume": 245931,
      "record_count": 943, "expected_count": 1055, "completeness_pct": 89.4,
      "finding_count": 1, "max_severity": "warning",
      "reconciliation": {
        "status": "compared", "ohl_agree": true,
        "supplied_close": 419.75, "close_diff": 0.50,
        "supplied_volume": 357198, "volume_ratio": 0.6885,
        "finding_ids": ["01H..."]
      }
    }
  ],
  "total": 2,
  "meta": {
    "bar_source": "derived_from_minute",
    "session_definitions": {
      "ES": {"window": "17:00-15:59", "timezone": "America/Chicago",
             "trade_date_rule": "roll at 17:00; trade date is the session close date",
             "expected_slots": 1380, "halt_windows": ["16:00-16:59"]},
      "ZC": {"windows": ["19:00-07:44", "08:30-13:19"], "timezone": "America/Chicago",
             "trade_date_rule": "roll at 17:00; trade date is the session close date",
             "expected_slots": 1055, "halt_windows": ["07:45-08:29", "13:20-18:59"]}
    },
    "excluded_records": 0,
    "excluded_reason_counts": {}
  }
}
```

`meta.excluded_*` makes cleaned volume defensible. `session_definitions` is **keyed by
root** — the sample spans multiple session profiles; a single boundary string would be
wrong for multi-root requests. `expected_slots` is per-root. `bar_source` states derived
vs supplied and mirrors `scope.frequency`.

### 5.2 VWAP

`vwap` echoes window and price basis. Formula and frame:
`specs/analytics-semantics.md` (rolling 15-minute section). Example — `ESZ25` session start
and cash open on 2025-11-20:

```json
{
  "scope": {"contracts": ["ESZ25"], "basis": "clean", "frequency": "minute",
            "frequency_defaulted": false},
  "window": "15m", "window_type": "trailing_time_range_inclusive",
  "price_basis": "typical",
  "partition": ["contract_id", "trade_date"],
  "data": [
    {"ts_utc": "2025-11-19T23:00:00Z", "vwap": 6700.166667,
     "window_volume": 1717, "window_records": 1, "is_warmup": true},
    {"ts_utc": "2025-11-20T14:30:00Z", "vwap": 6765.329481,
     "window_volume": 34330, "window_records": 15, "is_warmup": false},
    {"ts_utc": "2025-11-20T14:31:00Z", "vwap": 6766.622116,
     "window_volume": 45491, "window_records": 15, "is_warmup": false}
  ]
}
```

`vwap: null` with `window_volume: 0` is the correct undefined VWAP — no volume in the
window. Charts break the line; they must not interpolate.

**When the contract holds no minute records, `vwap` refuses** — not an empty `data` array,
not a zero-filled series, not a 15-day VWAP over daily bars:

```json
{
  "type": "/errors/frequency-unavailable",
  "title": "Minute records required",
  "status": 422,
  "detail": "GCJ26 holds daily records only. A rolling 15-minute VWAP requires intraday records; there is no intraday window to volume-weight. Upload the minute file for this contract to enable it.",
  "instance": "/v1/analytics/vwap?contract=GCJ26&window=15m",
  "code": "CAP.FREQUENCY_UNAVAILABLE",
  "meta": {"contract_id": "GCJ26", "requested_frequency": "minute",
           "frequencies_available": ["daily"], "substitute_offered": false}
}
```

**422** (not 404 or 400): the request is syntactically valid and the contract exists; the
server understands it and cannot process it given current data. `meta` and
`substitute_offered: false` let the client render a next action without a second call.

### 5.3 Compare

`compare=basis` — raw and clean side by side (cleaning impact).
`compare=frequency` — supplied daily vs derived-from-minute, field by field. Requires both
frequencies; returns the same `CAP.FREQUENCY_UNAVAILABLE` refusal when only one is held.

---

## 6. Data quality

```
GET  /v1/dq/summary?contract=&start=&end=&basis=&frequency=
GET  /v1/dq/metrics?contract=&start=&end=&frequency=&group_by=day|contract|rule|dimension|frequency&dimension=
GET  /v1/dq/findings?contract=&start=&end=&frequency=&rule_id=&severity=&status=&limit=&offset=
GET  /v1/dq/findings/{finding_id}
GET  /v1/dq/changelog?contract=&start=&end=&run_id=&limit=&offset=
GET  /v1/dq/rules
POST /v1/dq/runs
GET  /v1/dq/runs/{run_id}
```

**Extension (not v1):**

```
POST /v1/dq/findings/{finding_id}/review
POST /v1/dq/rules
PATCH /v1/dq/rules/{rule_id}
```

Score field semantics and weight policy: `specs/dq-rules-and-scoring.md`. This section
owns only the HTTP envelope.

### 6.1 Summary

Dashboard call — one request per page load. Unlike analytic endpoints, `frequency` accepts
a comma-separated list and **defaults to every frequency held** for the contracts in scope.
The resolved list is echoed. Example measured on sample `ESZ25` minute + daily:

```json
{
  "scope": {"contracts": ["ESZ25"], "start": "2021-06-04", "end": "2025-12-19",
            "basis": "clean", "frequencies": ["minute", "daily"],
            "frequency_defaulted": true},
  "overall_score": 97.7,
  "score_method": "weighted mean of in-scope dimension scores; overall = Σ(w×s) / Σ(w)",
  "dimensions_in_scope": ["completeness", "validity", "consistency", "uniqueness",
                          "timeliness", "reconciliation"],
  "dimensions_not_in_scope": [],
  "weight_denominator": 1.20,
  "scope_signature": "cmp+val+con+unq+tim+rec",
  "dimensions": [
    {"dimension": "completeness", "score": 98.8, "weight": 0.30,
     "expected_records": 95220, "actual_records": 94059, "findings": 12,
     "note": "Minute records inside the derived liquidity window 2025-09-15 to 2025-12-18, 69 sessions at 1380 slots."},
    {"dimension": "validity", "score": 99.9, "weight": 0.25, "findings": 27,
     "by_frequency": {"minute": 0, "daily": 27}},
    {"dimension": "consistency", "score": 99.4, "weight": 0.20, "findings": 7,
     "by_frequency": {"minute": 0, "daily": 7}},
    {"dimension": "uniqueness", "score": 100.0, "weight": 0.15, "findings": 0},
    {"dimension": "timeliness", "score": 100.0, "weight": 0.10, "findings": 0},
    {"dimension": "reconciliation", "score": 88.6, "weight": 0.20, "findings": 476,
     "conditional": true,
     "inputs": {"sessions_compared": 217, "sessions_complete_and_compared": 39,
                "sessions_minute_only": 7, "sessions_daily_only": 268,
                "ohl_disagreements_complete_sessions": 0,
                "ohl_disagreements_suppressed_incomplete": 126,
                "volume_shortfalls": 200, "median_volume_ratio": 0.9554,
                "close_convention_differs": 211}}
  ],
  "records": {"total": 115622, "by_frequency": {"minute": 114477, "daily": 1145},
              "excluded": 7, "rejected_at_load": 0},
  "top_issues": [
    {"rule_id": "REC.VOLUME_SHORTFALL", "findings": 200, "affected_sessions": 200,
     "severity": "info"},
    {"rule_id": "REC.SESSION_ONLY_IN_ONE", "findings": 275, "affected_sessions": 275,
     "severity": "info"},
    {"rule_id": "VAL.ZERO_VOLUME_WITH_RANGE", "findings": 26, "affected_rows": 26,
     "severity": "info"},
    {"rule_id": "CON.CLOSE_OUT_OF_RANGE", "findings": 6, "affected_rows": 6,
     "severity": "error"}
  ],
  "meta": {
    "weights_applied": {"completeness": 0.30, "validity": 0.25, "consistency": 0.20,
                        "uniqueness": 0.15, "timeliness": 0.10, "reconciliation": 0.20},
    "weight_denominator": 1.20,
    "weight_policy": "renormalise over dimensions in scope: overall = Σ(w×s) / Σ(w). Reconciliation weight 0.20 is omitted from both sums when the contract holds only one frequency, so the denominator is then 1.00. See specs/dq-rules-and-scoring.md.",
    "min_support": 100
  }
}
```

**Which dimensions were in scope is part of the score, not metadata about it.**
`dimensions_in_scope`, `dimensions_not_in_scope` (with reason), `weight_denominator`,
`scope_signature`, and applied weights stop clients treating unequal scopes as equivalent.
Equal `scope_signature` → comparable; unequal → the UI must say so.

Minute-only shape:

```json
{
  "dimensions_in_scope": ["completeness", "validity", "consistency", "uniqueness", "timeliness"],
  "dimensions_not_in_scope": [
    {"dimension": "reconciliation",
     "reason": "Only minute records are held for ESZ25. Reconciliation compares supplied daily bars against bars derived from the minute tape and requires both."}
  ],
  "weight_denominator": 1.00,
  "scope_signature": "cmp+val+con+unq+tim"
}
```

`REC.OHLC_DISAGREE` is gated on complete minute sessions (`specs/dq-rules-and-scoring.md`);
the API surfaces the effect as per-bar `reconciliation.status` of `compared` or
`not_comparable`.

**`contracts[]` — the inventory row, alongside `slices[]`.** `slices` is per contract ×
frequency; every persona's Summary table is one row per *contract*
(`specs/loupe-ui-design.md`). The rollup is composed in `quality`, not by the client:

```json
{
  "contracts": [
    {"contract_id": "ZCZ25", "score": 41.0, "status": "ATTN",
     "frequencies": ["daily", "minute"], "finding_count": 9,
     "top_issue": {"rule_id": "CON.CLOSE_OUT_OF_RANGE", "label": "Close outside the bar range",
                   "severity": "error", "findings": 6},
     "settlement_issue": {"rule_id": "CON.CLOSE_OUT_OF_RANGE",
                          "label": "Close outside the bar range",
                          "severity": "warning", "findings": 2}}
  ],
  "worst_field": {"field": "close", "findings": 6, "considered": 7, "total": 23}
}
```

`score` is the **minimum** across the contract's slices — as trustworthy as its worst
frequency. A record-weighted mean would let a large clean minute tape bury a broken daily
file. The page-level `overall_score` is unchanged and remains the unweighted mean of slices.

`status` is `ATTN` when the contract holds any open `error` or `critical` finding, `OK`
otherwise. Severity, never a score threshold: §11.5 of `specs/dq-rules-and-scoring.md` has
the score as a navigation index rather than a grade.

**Two callouts ship on every row, not one behind a parameter.** `top_issue` is the worst
issue of any kind; `settlement_issue` is drawn from `SETTLEMENT_RULES` at daily grain only
(§11.6) and is null for a contract held solely at minute grain. Personas are a UI view
selector and nothing in this contract is persona-aware (§8), so a `?callout=` parameter would
make the endpoint persona-shaped to save one string per row. Both carry the rule's own
`label` from `dq.dq_rule.name`, so wording lives with the rule rather than in a widget.

`worst_field` is derived from rule identity (§11.7) and is `null` — the tile reads "not
applicable" — when a scope's findings are all from unmapped rules. It is never a group-by
over `dq.dq_finding.details`, which is evidence and not a key.

**It carries its denominator**, for the reason §11.5 makes a score carry one. `findings` is
the winning field's count, `considered` is how many open findings name a field at all, and
`total` is every open finding in scope. The three are routinely far apart — §11.7 excludes
field-parametric, record-shaped and diagnostic rules — so a client that showed the field
alone would imply it summarised everything on the screen.

**`dimension` on `/dq/metrics`.** `group_by=day` averages the dimensions together, which
cannot express a single-dimension trend. The Risk **Settlement trend** sparkline is
`completeness` at `frequency=daily` over trade dates, so the filter selects one dimension and
is echoed as `dimension` on the response. Omitted, behaviour is exactly as before.

### 6.2 Findings (v1 read-only)

Paginated. A corrupt file can still produce tens of thousands of rows:

```json
{
  "data": [
    {
      "finding_id": "01H...", "rule_id": "CON.CLOSE_OUT_OF_RANGE",
      "contract_id": "ESZ25", "trade_date": "2025-12-19",
      "ts_start_utc": "2025-12-19T21:00:00Z", "ts_end_utc": "2025-12-19T21:00:00Z",
      "severity": "error", "affected_rows": 1, "status": "open",
      "frequency": "daily",
      "details": {"field": "close", "close": 6768.25, "low": 6769.50, "high": 6856.50},
      "corroboration": {
        "state": "confirmed",
        "reason": "Vendor open, high and low agree with the minute tape for this session.",
        "detail": {"minute_coverage_pct": 99.1, "close_gap_ticks": 2}
      },
      "source": {"batch_id": "01H...", "filename": "ESZ25.parquet",
                 "source_row": 1145}
    }
  ],
  "total": 7, "limit": 100, "offset": 0
}
```

`source` carries `source_row` so the UI can cite "row 1,145 of `ESZ25.parquet`".

**`corroboration` — what the tape says about a daily finding (§8.7 of
`specs/dq-rules-and-scoring.md`).** It rides on the finding rather than on a route of its own,
because it is not a fact about the corpus but a *qualification of this finding*: shipping it
anywhere else would let a client render the finding without it.

`state` is one of three, and they are not interchangeable:

```json
{"state": "disputed",
 "reason": "The minute tape found prints above the stated high.",
 "detail": {"field": "high", "ticks": 3, "finding_ids": ["01H..."]}}
```
```json
{"state": "not_comparable",
 "reason": "Only daily records are held for ZCZ25.",
 "detail": {"minute_coverage_pct": null}}
```

`confirmed` licenses reading the finding as being about the close: the range around it is
measured correctly. `disputed` says the stated range is itself wrong, so the same finding must
be re-read as a range defect — `detail.finding_ids` cites the `REC.OHLC_DISAGREE` rows that
say so. `not_comparable` licenses neither, and exists so that "we could not check" is never
rendered as "we checked and it holds".

**Null is a fourth answer and means something else.** `corroboration` is absent on findings
corroboration does not apply to — a minute-grain timeliness finding is not a claim the daily
file can speak to. Absent means *not applicable*; `not_comparable` means *applicable but
unevaluable*, because one granularity is held, the session falls outside the reconcilable
window (§8.5), or minute coverage is below `params.min_coverage_pct`.

It is computed, never stored: no column on `dq.dq_finding`, no finding of its own, and no
contribution to any score (§8.6's numerator is unchanged). Both `GET /v1/dq/findings` and
`GET /v1/dq/findings/{id}` carry it, resolved in one pass over the run's `REC.*` findings
rather than per row.

### 6.3 Finding review — extension

```json
{ "status": "overridden", "note": "Expiry-day settlement sits outside the traded range; expected." }
```

`POST /v1/dq/findings/{id}/review` is **not v1**. v1 UI shows suggestion text only; no override.

### 6.4 Rules and runs

`GET /v1/dq/rules` returns the catalogue. `POST /v1/dq/runs` re-validates a scope under the
current ruleset, blocks until finished, and returns the completed run summary (`run_id`,
status, `ruleset_hash`, findings count, elapsed). `GET /v1/dq/runs/{run_id}` retrieves a
past run — not a pending job handle.

`POST` / `PATCH` `/dq/rules` (catalogue mutation so an accepted suggestion can take effect)
are **extensions**, paired with suggestion apply.

### 6.5 Changelog (v1 read-only)

What default cleaning decided, so a clean series can show its working. `dq.cleaning_action`
is the store; this is its only read path.

```json
{
  "scope": {"contracts": ["ESZ25"], "start": "2025-06-02", "end": "2025-06-30"},
  "run_id": "01H...",
  "data": [
    {"contract_id": "ESZ25", "trade_date": "2025-06-12", "frequency": "minute",
     "rule_id": "CMP.MISSING_TIMESTAMP", "label": "Missing timestamps",
     "action": "exclude", "records": 4},
    {"contract_id": "ESZ25", "trade_date": "2025-06-18", "frequency": "minute",
     "rule_id": "UNQ.EXACT_DUPLICATE", "label": "Exact duplicate",
     "action": "dedupe_drop", "records": 1}
  ],
  "total": 2, "limit": 100, "offset": 0
}
```

**Aggregated by rule x trade date x action, never one row per record.** The panel row is a
count ("excluded 4 open slots"), so a per-record route would leave the client summing them,
and aggregation is outside `ui` (`specs/loupe-solution-design.md` §6).

`dq.cleaning_action` carries neither `contract_id` nor `trade_date` — it keys on `record_id` —
so both come from joining `stage.market_record`, which is where they are authoritative.

`run_id` defaults to the latest succeeded run, resolved as §6.1 resolves it, and may be passed
explicitly so a past run stays inspectable after a later one supersedes it. A decision with a
null `rule_id` is labelled null rather than dropped: an action nobody can attribute is exactly
what an audit trail must still show.

**Read-only, and not because v1 is cautious.** Default cleaning is automatic policy driven by
severity, not a user action (`specs/dq-rules-and-scoring.md` §14), so there is no request a
client could make here. Overriding a finding is the extension (§6.3), and it changes findings
rather than these rows.

---

## 7. Insights

```
GET  /v1/insights/patterns?contract=&start=&end=&min_lift=&min_support=
GET  /v1/insights/suggestions?contract=&start=&end=
```

**Extension (not v1):**

```
POST /v1/insights/suggestions/{id}/apply
POST /v1/insights/suggestions/{id}/dismiss
```

Pattern and suggestion object shapes: `specs/dq-rules-and-scoring.md`. This section owns
the routes and the apply response envelope only.

### 7.1 Apply — extension

Apply writes the proposed change to `dq.dq_rule` or `ref.session_calendar`, re-runs the
affected scope in the same request, and returns the run alongside before/after scores:

```json
{ "applied": true, "run_id": "01H...", "findings_count": 61,
  "score_before": 91.0, "score_after": 95.1 }
```

v1 surfaces suggestions as report-only text (exercise: identify and suggest, not mutate).

---

## 8. Authentication

**None in v1.** Personas are a UI view selector, not an authorisation boundary. Nothing in
this contract is persona-aware.

**Extension:** auth dependency at the FastAPI router level, role claim, filter `contract`
scope per role. **No endpoint signature changes** — the API is resource-shaped, not
view-shaped.

---

## 9. Endpoint-to-requirement traceability

Keep this table in the delivered README.

| Exercise requirement | Endpoint |
|---|---|
| Accept CSV or Parquet | `POST /v1/ingest/preview`, `POST /v1/ingest/batches` |
| Process Contract/Timestamp/OHLCV | `POST /v1/ingest/batches`, `GET /v1/contracts` |
| Handle missing, duplicate, malformed | `GET /v1/ingest/batches/{id}/rejects`, `GET /v1/dq/findings` |
| Daily OHLCV bars | `GET /v1/analytics/bars/daily` |
| Rolling 15-minute VWAP | `GET /v1/analytics/vwap` |
| Filter by contract and date range | query parameters on every analytic and DQ endpoint |
| Missing timestamps and gaps | `GET /v1/dq/findings?rule_id=CMP.MISSING_TIMESTAMP` |
| Duplicate records | `GET /v1/dq/findings?rule_id=UNQ.*` |
| Invalid prices or volumes | `GET /v1/dq/findings?rule_id=VAL.*` |
| Statistical outliers (optional) | `GET /v1/dq/findings?rule_id=OUT.*` |
| Recurring DQ patterns | `GET /v1/insights/patterns` |
| Suggest cleansing/validation rules | `GET /v1/insights/suggestions` (apply is extension) |
| Cross-granularity reconciliation | `GET /v1/dq/findings?rule_id=REC.*`, `GET /v1/analytics/compare?compare=frequency` |
