# Loupe

Loupe is a local, first-scan application for assessing the quality of historical futures
data and seeing what the usable series looks like.

It combines deterministic data-quality checks with daily OHLCV bars and rolling 15-minute
VWAP. It is intentionally not a trading workstation, a warehouse, or a live-feed system.

Stack: Python 3.12+, Streamlit, FastAPI, and DuckDB.

## Quick start

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
```

Start the API and UI in separate terminals:

```bash
uv run uvicorn loupe.api.app:create_app --factory
```

```bash
uv run streamlit run src/loupe/ui/app.py
```

Open <http://localhost:8501>. The API is at <http://127.0.0.1:8000/v1>, with generated
OpenAPI documentation at <http://127.0.0.1:8000/v1/docs>.

The first API start creates `data/loupe.duckdb`, applies the schema, and seeds reference
data and the quality-rule catalogue. Set `LOUPE_DB` to use another store. Set
`LOUPE_API_URL` to point the UI at another API base URL.

To permanently delete all local Loupe data and start with a fresh database, stop the API
and UI, then run from the repository root:

```bash
uv run python -c "from pathlib import Path; from loupe.data import database_path; p = database_path(); files = () if str(p) == ':memory:' else (p, Path(str(p) + '.wal')); [f.unlink(missing_ok=True) for f in files]"
```

This command works in Bash, PowerShell, and Command Prompt, respects `LOUPE_DB`, and removes
the write-ahead log if one exists. The next API start recreates and seeds the database.

## Primers and Worked Examples
* [`docs/metrics-primer.md`](docs/metrics-primer.md) - scroll-through of Loupe and explanation of metrics as you see them **(Recommended)**
* [`docs/how-loupe-works.md`](docs/how-loupe-works.md) - detailed end-to-end code map 

## Walkthrough

1. Open **Overview**, the default landing page.
2. Select **Load demo data**. Loupe fetches the pinned vendor sample only after this explicit
   action, converts two selected Parquet files to CSV, ingests both formats, runs quality
   checks, and builds the marts. The sample is fetched because it has no redistribution
   licence; it is never committed.
3. Scan one row per loaded contract and held grain. The four family columns show headline
   counts for **Gaps**, **Duplicates**, **Invalid values**, and **Recurring patterns**.
4. Select a row to open **Review** with that contract and quality grain.
5. For a dual-grain contract such as `ESZ25`, switch **Quality grain** between Minute and
   Daily. Cards, issues, picture, OHLCV source, and overlays all follow that choice.
6. Select a family card. The Daily OHLCV chart marks only that family; the issues table and
   picture describe the same evidence. Zoom the OHLCV and rolling 15-minute VWAP charts
   independently.
7. Optionally select **Inject demo defects**. Loupe writes a labelled copy, never changes the
   vendor file, and discloses synthetic records on every rerun. **Remove demo defects**
   restores the clean file.

The vendor corpus is close to defect-free. The separate injector makes otherwise unreachable
checks visible without presenting planted defects as vendor facts.

To fetch the sample without the UI:

```bash
uv run python tools/fetch_samples.py --csv
```

Arbitrary CSV and Parquet ingestion remains available through the API. The v1 UI deliberately
uses the curated demo path rather than hosting a second upload workflow.

## Architecture

```text
Browser
  │
  ▼
Streamlit UI ── HTTP/JSON ──► FastAPI /v1
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
                 quality      insights       data
                    └────────────┼────────────┘
                                 ▼
                              DuckDB
```

The boundaries are functional:

- `data` loads and queries DuckDB.
- `quality` runs checks, scores, cleaning rules, reconciliation, and pattern detection.
- `insights` derives bars, VWAP, comparisons, and publish-gate results.
- `api` exposes typed HTTP envelopes over those services.
- `ui` is a thin HTTP client. Streamlit callbacks contain no SQL, scoring, or bar math.

FastAPI owns one locked DuckDB connection. That fits the single-user design and protects
temporary assessment tables from concurrent requests; it is not a multi-user architecture.

## Data and calculation choices

1. **Raw records are immutable.** Cleaning produces a derived view and a replayable
   changelog; it never edits source rows in place.
2. **Exchange-local time is authoritative.** UTC is derived at ingest, and the timezone
   decision is recorded with the batch.
3. **A day means a per-root trading session, not a calendar date.** The sample includes
   three session profiles. The common CME-family profile has 1,380 expected minute slots.
4. **VWAP is a trailing 15-minute time window.** It is partitioned by contract and trade
   date and never crosses a session. Undefined values remain `NULL`.
5. **Rules are deterministic and data-driven.** Rule definitions and weights are seeded
   as rows. AI is limited to a possible future narrative over aggregate statistics.
6. **The UI has Overview and Review, not role-specific views.** There is no authentication
   in v1.
7. **Ingestion is synchronous.** This keeps the local workflow inspectable; asynchronous
   jobs become worthwhile only above the current sample scale.
8. **Daily and minute inputs are both accepted.** Capability follows the supplied grain.
   Daily-only data gets bars and checks but not a fabricated 15-day substitute for VWAP.
9. **Fetching and ingest are separate.** Ingest never contacts the network.
10. **Findings and suggestions are report-only in the UI.** Coded cleaning rules still
    produce the clean view and changelog; users do not apply or dismiss suggestions in v1.

## Quality semantics

Loupe seeds 38 rules across completeness, validity, consistency, uniqueness, timeliness, and
cross-frequency reconciliation. The four UI families are a reviewer-facing grouping, not the
complete catalogue; statistical `OUT.*` rules stay off the strip.

The API computes a 0–100 score as a weighted mean over dimensions in scope. It is a navigation
tool, not a grade. Every score carries a `scope_signature`, and an undersized scope returns an
absent score with `insufficient_data`, not zero. Neither UI page currently draws the score.

Reconciliation requires both daily and minute data. A batch-scoped run only assesses that
batch, so API callers must run corpus-wide `POST /v1/dq/runs` after the companion grain arrives.
**Load demo data** already does this. In the measured ES sample, open/high/low reconcile
exactly over 67 coverage-gated sessions, while 18 closes differ because settlement can be
nearer the last trade than the configured 15:00 print.

## API coverage

| Requirement | Endpoint |
|---|---|
| Accept CSV or Parquet | `POST /v1/ingest/preview`, `POST /v1/ingest/batches` |
| Process Contract/Timestamp/OHLCV | `POST /v1/ingest/batches`, `GET /v1/contracts` |
| Handle missing, duplicate, malformed rows | `GET /v1/ingest/batches/{id}/rejects`, `GET /v1/dq/findings` |
| Daily OHLCV bars | `GET /v1/analytics/bars/daily` |
| Rolling 15-minute VWAP | `GET /v1/analytics/vwap` |
| Filter by contract and date | Query parameters on analytic and DQ endpoints |
| Missing timestamps and gaps | `GET /v1/dq/checks?family=gaps`, `GET /v1/dq/findings?rule_id=CMP.MISSING_TIMESTAMP` |
| Duplicate records | `GET /v1/dq/checks?family=duplicates`, `GET /v1/dq/findings?rule_id=UNQ.*` |
| Invalid prices or volumes | `GET /v1/dq/checks?family=invalid`, `GET /v1/dq/findings?rule_id=VAL.*` |
| Statistical outliers | `GET /v1/dq/findings?rule_id=OUT.*` |
| Recurring patterns | `GET /v1/dq/checks?family=patterns`, `GET /v1/insights/patterns` |
| Suggest cleansing or validation rules | `GET /v1/insights/suggestions` |
| Cross-granularity reconciliation | `GET /v1/dq/findings?rule_id=REC.*`, `GET /v1/analytics/compare?compare=frequency` |

## Trade-offs and limitations

- Two processes preserve a real UI/API boundary, at the cost of two startup commands.
- Streamlit keeps the interface small and testable, but reruns the script on interaction and
  has no server push.
- Overview currently requests `/dq/checks` once per contract and grain, cached against the
  store fingerprint. A bulk endpoint should be added only if measurement shows this loop is
  too slow.
- DuckDB makes analytics inspectable and local, but the single locked connection is designed
  for one user and one writer.
- A daily-only contract keeps the VWAP panel and says **needs minute bars**.
- Pattern `field` and `rule` dimensions have no exposure denominator, so lift is undefined.
- Three suggestion generators remain absent because grouped findings lack per-finding field
  attribution.
- The configured settlement mark is seeded only for the default CME profile. Unsupported
  roots under-report rather than make an unjustified comparison.
- The sample calendar is measured from the supplied corpus, not a complete holiday service
  for every venue.
- Continuous or back-adjusted series, live feeds, multi-user concurrency, and telemetry are
  outside v1.

## Extending Loupe

- **New rule:** add a catalogue entry, a focused runner, and a fixture; seed it into
  `dq.dq_rule`.
- **New vendor layout:** extend ingest column mapping and preview validation.
- **New root or venue:** seed product, timezone, tick, and session-calendar facts. Do not infer
  a new venue from the existing CME defaults.
- **Larger ingest:** introduce a job table and polling when synchronous load exceeds the
  documented threshold.
- **Workflow features:** finding override and suggestion apply/dismiss fit behind new API
  routes without changing immutable raw data.
- **AI narrative:** operate only on aggregated pattern statistics; raw ticks stay local.

## Development

```bash
git config core.hooksPath .githooks
uv run pytest
uv run ruff check .
```

Tests requiring the fetched corpus are marked `samples` and skip when it is absent. The suite
also includes a real-process integration tier, API contract tests, DuckDB rule/query tests,
and Streamlit `AppTest` coverage. The test map is
[`docs/how-tests-work.md`](docs/how-tests-work.md).

Product and calculation truth lives in [`specs/`](specs/). Execution status lives in
[`plans/`](plans/). [`docs/how-loupe-works.md`](docs/how-loupe-works.md) is the detailed
end-to-end code map. `_notes/` is local research and is not normative.
