# Loupe — Solution Design

Refined design for the Market Data Quality & Analytics exercise.

Revised 2026-09-07: v1 UI ingest is Load demo data; capability preview is API-only
and disclosed in place on the dashboard (slice 8).
Revised 2026-09-06: `specs/api-contract.md` promoted (slice 4 done-when 1).
Revised 2026-09-05: `specs/analytics-semantics.md` promoted (slice 3 done-when 1).
`specs/dq-rules-and-scoring.md` promoted (slice 2). Slice 1 specs (`data-model.md`,
`sample-corpus.md`) already promoted. Remaining sibling: UI only (slice 5).

This document is the implementation brief. **`specs/` is normative.** Calculation, schema,
rule catalogues, API payloads, and UI belong in `specs/` (this brief plus sibling specs).
`_notes/` is a research scrapbook and is not implementation law. `_notes/founding/` is a
locked historical record. Where a spec and a note disagree, the spec wins. If a topic is
still only documented under `_notes/cursor/`, promote it into `specs/` before treating it
as binding. Execution sequence: `plans/`.

| Detail | Document |
|---|---|
| Persona UI, Summary / Specifics, wireframes, tooltips | `specs/loupe-ui-design.md` |
| Analytics semantics (bars, VWAP, grid) | `specs/analytics-semantics.md` |
| Data model / DDL | `specs/data-model.md` |
| DQ rules and scoring | `specs/dq-rules-and-scoring.md` |
| API contract | `specs/api-contract.md` |
| Sample corpus / oracle claims | `specs/sample-corpus.md` |
| Futures domain primer | Research only: `_notes/cursor/01-futures-data-primer.md` (not a v1 product spec) |
| Founding journeys (locked historical) | `_notes/founding/loupe-solution-design.md` |

---

## 1. Positioning

Loupe is a **first-scan** tool for historical futures data.

- Lightweight discovery before formal, static reporting
- Answers two questions:
  - **Can I trust this data?** — confidence, quality score, findings, changelog
  - **What does this data look like?** — OHLCV bars, VWAP, filters, overlays

**Context + Data = Information.** The UI exists to make that combination legible, not to be a
trading workstation or a data warehouse.

### Assumptions

- Requirements change slowly; the product has semi-rigid boundaries. Extensions that warp those
  boundaries belong in a different application.
- Single user, local process — no high availability, no multi-tenant concurrency.
- Historical data only; not live feeds.
- Single DuckDB file; no backups, no secondary stores, no Redis, no auth service unless asked.
- Telemetry is out of scope.

---

## 2. Personas

Personas are a **UI view selector**, not an authorisation boundary. No authentication in v1;
RBAC is a documented extension that filters contract scope without changing endpoint signatures.

| Persona | Primary need | What they look at |
|---|---|---|
| **Risk manager** | Is the daily close / settlement trustworthy? How much of the book is affected? | Book grain: score, contracts needing attention, session completeness, settlement-quality sparkline, worst-first list with closing-day callouts. Specifics: Why / Impact / Address, daily OHLCV with quality on the candle, raw vs clean. No tick drill-down, no outlier hunting. |
| **Trader** | Can I use this series for backtesting / charts? | Name-sorted list (Root, Contract, Score, Warning). Specifics: one contract, window completeness, warnings, changelog marks on the **clean** series (click row ↔ mark; raw ghost where it disagrees), OHLCV + 15-min VWAP (refused in place if daily-only). Score carries go/no-go; no GO/NO column. |
| **Analyst** | What is broken, and what would we cleanse? | Score-then-name list with finding counts. Specifics: read-only findings log, raw neighbourhood of the selected finding, patterns (lift), suggestions as text, engine changelog, diagnostic charts including daily-vs-minute when both exist. **v1 does not override findings or apply suggestions from the UI.** |

Illustrative trader question — *"I want to backtest ES through a wild market. How clean is this
data?"* — remains valid. The shipped sample runs **2021–2026**, so demos use a volatile window
inside that range rather than 2008.

### Advise Risk users to load both grains

**Every persona can use Loupe independently, on the grain they arrive with.** A Trader with
only the minute tape gets bars, VWAP, warnings and a changelog — a real answer to *is this
series usable*. An Analyst works with whatever is there and is told what is not. Nothing here
is a prerequisite, and no upload is refused for arriving alone.

**The Risk manager is the exception, and the advice is aimed at them.** Theirs is the one
persona whose primary question cannot be fully answered from their own primary grain. Daily
is the Risk grain — settlement is what the book is marked at — but a daily file can only be
checked against itself: close inside the bar range, on the tick, not duplicated, session
present. Nothing in that set can catch a settlement file that is internally perfect and still
wrong. Only `REC.*` can (§9), and only when the minute tape is there to compare against.

So the recommendation is specific rather than general: **a Risk user should load the minute
tape alongside the daily file for the contracts they care about.** It is the Trader's primary
grain, and reconciling one against the other is what turns "this file is self-consistent" into
"this settlement is corroborated". Where the two disagree, the Analyst's Specifics view is
where that gets investigated.

The reason it needs saying out loud is that the failure is silent. A **minute-only** contract
makes the Risk view visibly thin — no closing-day callouts, no settlement trend, both measured
on the daily file — so the reader can see they are not being told much. A **daily-only**
contract makes the Risk view look *complete*: every column fills and the score computes, but
reconciliation is out of scope, §11.3 renormalises the denominator from 1.20 to 1.00, and a
five-dimension measurement is displayed on the same 0–100 scale as a six-dimension one.

**One grain scores what a file says about itself; two grains score whether it is true.** Where
a contract holds one, every surface that shows a score must say which dimensions were in scope
(`specs/dq-rules-and-scoring.md` §11.3), and the missing companion grain is named as advice —
on `POST /v1/ingest/preview` for API callers, and in place on the dashboard after load, in
the terms of the persona it matters to, never as a gate. The v1 UI does not host a pre-commit
preview panel.

---

## 3. Locked decisions

These are no longer open. State them in the delivered README.

1. **Raw records are immutable.** Cleaning is a derived view driven by rules. The changelog is a
   replayable log of rule applications, never an audit of in-place edits.
2. **Exchange-local wall clock is the source of truth; UTC is derived.** Session logic runs in
   local time; `ts_utc` is produced at ingest and recorded as a batch decision.
3. **A "day" is a trading session, not a calendar date**, and the session is **per-root**. CME
   family: 17:00 CT previous day → 16:00 CT. This corpus has three session profiles (including
   ZC with two windows). A full CME-family minute session is **1,380** slots — not 1,365; there
   is no 15:15–15:30 halt in this sample.
4. **Rolling 15-minute VWAP** means a trailing time window (`RANGE` on timestamps), partitioned
   by `(contract, trade_date)`, never spanning sessions or contracts. Undefined VWAP is `NULL`,
   not zero or forward-filled.
5. **Rules are deterministic and data-driven.** AI is a documented narrative extension only;
   raw market data never leaves the process.
6. **No authentication.** Personas = view selector.
7. **Ingestion is synchronous.** Streamlit has no server push; at sample scale a job table buys
   nothing. Async is an extension if ingest exceeds ~30s; enforce a hard upload size cap.
8. **Both granularities are accepted; capability follows from input.** Gate on CSV/Parquet only,
   never on daily vs minute.
9. **Sample data is fetched at setup time**, via a pinned script and optionally a "Load demo
   data" button — never as a runtime dependency during ingest.
10. **v1 findings and suggestions are report-only.** The engine still applies **coded** rules
    (immutable raw, derived clean view, changelog). Analyst Override and suggestion
    apply / dismiss are extensions — the exercise asks to identify and suggest, not to mutate
    the catalogue from the UI.

---

## 4. Capability model

Capability follows from what was supplied. **The v1 UI does not host a pre-commit preview
panel.** `POST /v1/ingest/preview` stays as an API dry run (and for any non-UI caller). Demo
load already skips per-file preview (`validate=False`, then one corpus-wide run). The
dashboard discloses what is unavailable **in place** after load — a daily-only contract keeps
the VWAP panel and says "needs minute bars"; a daily-only score caption names the missing
companion grain. There is no sidebar capability matrix before commit.

| Uploaded | Daily OHLCV | Rolling 15-min VWAP | Reconciliation (`REC.*`) |
|---|---|---|---|
| Minute only | Derived | Yes | No |
| Daily only | Ingested as-is | Unavailable (structured refusal, not empty chart) | No |
| Both | Derived **and** compared | Yes | Yes |

Do not invent a 15-*day* VWAP from daily bars and label it as the exercise requirement.

**Why accept daily.** Every naturally occurring defect in the sample lives in the daily files;
the minute tape is essentially clean. Risk managers work on settlement series. Rejecting daily
would also make user-supplied reconciliation impossible and force a runtime HuggingFace
dependency — which we reject.

---

## 5. Requirements traceability

| Exercise requirement | Design response |
|---|---|
| Accept CSV or Parquet | Preview + sync ingest; column mapping recorded on batch |
| Process Contract, Timestamp, OHLCV | Mapped to `contract_id`, `ts_*`, OHLCV (+ optional `open_interest`) |
| Handle missing / duplicates / malformed | Row-level rejects + findings; partial accept; immutable raw + clean view |
| Daily OHLCV bars | Positional open/close, extremal high/low; quality annotation on the bar |
| Rolling 15-minute VWAP | Trailing `RANGE` window; typical price default; `basis=raw\|clean` |
| Filter by contract and date | Query params on every analytic / DQ endpoint; dates are **trade dates** |
| Missing timestamps / gaps | Expected grid from session calendar − halt windows; run-length findings |
| Duplicates | Exact dup vs key conflict; different severities and cleaning |
| Invalid prices / volumes | Validity + consistency catalogue; off-tick via `ref.tick` |
| Statistical outliers (optional) | MAD on log returns; `info`; never auto-exclude |
| Recurring DQ patterns | Lift over hour / DOW / contract / field / batch / frequency; risk sees a settlement-quality sparkline, analyst sees the lift table |
| Suggest cleansing / validation rules | Report suggestions with rationale / `expected_effect`. Apply → `dq_rule` / calendar → re-run is an **extension** |
| Clean / extensible architecture | Layers below; rules and mappings as data |
| Tests + edge cases | Fixtures + oracle + measured baselines |

---

## 6. Architecture

```
┌─────────────┐     HTTP /v1      ┌─────────────┐      SQL       ┌────────────┐
│  Streamlit  │ ───────────────►  │   FastAPI   │ ─────────────► │  DuckDB    │
│     UI      │ ◄───────────────  │     API     │ ◄───────────── │  *.duckdb  │
└─────────────┘                   └─────────────┘                └────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
               quality/             insights/              data/
               rules, score,        bars, VWAP,            load, query,
               patterns, REC        compare                calendar, marts
```

### Layers (keep separate)

| Layer | Owns | Does not own |
|---|---|---|
| `quality` | Rules, findings, score, patterns, suggestions, reconciliation | Charts, Streamlit widgets |
| `insights` | Daily bars, VWAP, raw/clean compare | SQL loaders, DQ rule definitions |
| `data` | DuckDB connect, ingest, reference seed, marts | UI, HTTP |
| `api` | FastAPI routes, Pydantic models | Business math duplicated in handlers |
| `ui` | Streamlit pages, thin API clients | SQL, rule logic, aggregation |

No SQL, quality rules, or insight maths in Streamlit callbacks.

### Tech stack and trade-offs

| Choice | Why |
|---|---|
| **Python** | Exercise-native; one language across UI, API, analytics |
| **Streamlit** | Fast business UI; progress around sync ingest (`st.status`) |
| **FastAPI** | Typed contract, OpenAPI as architecture evidence, testable with `TestClient` |
| **DuckDB** | SQL as inspectable analytics; out-of-core; single-file persistence matches single-user assumption |

**DuckDB vs Polars.** Polars is strong for repeatable in-memory transforms; DuckDB wins here
because analytics stay as reviewable SQL, persistence and query share one engine, and the
single-writer constraint is the *reason* for the single-user assumption rather than a coincidence.

---

## 7. Data strategy

### Source corpus

HuggingFace dataset `lynx1231/historical-futures-data-sample` (public evaluation sample):

- 40 contracts, 8 roots (`CL`, `ES`, `GC`, `SB`, `SR3`, `VX`, `ZC`, `ZN`), 6 exchanges
- Configs: `data/daily/` and `data/minute/`
- Observed: 1-minute bars, `America/Chicago` wall clock, interval-start stamps, `contract_symbol`
  on every row
- **No licence grant** → fetch into gitignored `data/samples/`; never commit vendor Parquet
- Setup: `tools/fetch_samples.py` pinned to revision + checksums; optional UI "Load demo data"

### Ingestion principles

- Preview first (API): headers, types, inferred timezone / interval / frequency, capability matrix.
  The v1 UI does not host this panel.
- Sync `POST /v1/ingest/batches` → **201** with finished summary (`dq_run_id`, row counts, elapsed)
- Idempotent on `file_hash` (409 if duplicate)
- Parse failures → `stage.record_reject`; nulls and soft defects → load + find
- Frequency discriminator on every record: `(contract_id, frequency, ts_utc)` — loading daily and
  minute without it collides
- **Name the companion grain** (§2, "Advise Risk users to load both grains"):
  a daily file with no minute tape for that contract cannot be reconciled, which is the one
  gap that matters to the Risk manager's question. Neither file is refused and neither is
  incomplete on its own terms. The API preview says what the second file would add; the v1
  UI says the same in place after load.

### Oracle (test asset, not runtime)

Vendor daily vs minute-derived daily: **open / high / low** agree on ~96.5% of complete sessions.
Close is settlement (not last trade); volume on the tape is ~95% of reported daily. Use the
oracle to **test** an independently chosen definition — never to derive one. Claim: "agrees with
vendor daily bars," not "verified correct."

---

## 8. Analytics semantics (summary)

Full definitions: `specs/analytics-semantics.md`.

### Trade date

Session attributed to the date it **closes**. For CME open at 17:00 local:

- `local_time < 17:00` → that calendar date  
- `local_time ≥ 17:00` → next calendar date  

Naive `GROUP BY date(timestamp)` misattributes every overnight bar. A full session and a full
calendar day are both 1,380 minute slots for CME-family roots — a count-only test passes while
membership is wrong.

### Daily OHLCV

| Field | Rule |
|---|---|
| Open | First record by `ts_utc` (tie-break `source_row`) |
| High / Low | `max(high)` / `min(low)` |
| Close | Last record by `ts_utc` |
| Volume | `sum(volume)` |

Carry on every bar: `completeness_pct`, `finding_count`, `max_severity`, `basis` (`raw`|`clean`),
and `source_frequency` (`minute` derived vs `daily` supplied).

### Rolling 15-minute VWAP

- Price basis: typical `(H+L+C)/3` by default  
- Window: `RANGE BETWEEN INTERVAL 15 MINUTES PRECEDING AND CURRENT ROW`  
- Partition: `(contract_id, trade_date)`  
- Zero window volume → `NULL` (break the line)  
- Warm-up flag for first 15 minutes of each session  

---

## 9. Data quality

Full catalogue, score formula, pattern/suggestion shapes, and fixture map:
`specs/dq-rules-and-scoring.md`.

### Dimensions

Completeness, uniqueness, validity, consistency, timeliness, and conditional
**reconciliation**. Rules are rows in `dq.dq_rule` (IDs like `CMP.*`, `UNQ.*`, `VAL.*`, `CON.*`,
`TIM.*`, `REC.*`, optional `OUT.*`).

### Reconciliation (`REC.*`)

Only when both frequencies exist for the same contract. Findings include OHLC disagreement
(coverage-gated), volume shortfall (one direction), session only-in-one, and close-convention
info. This is the only family that can catch errors in data that is internally perfect.

### Score

Per-dimension 0–100 sub-scores; overall = weighted mean over **dimensions in scope**.

Default weights: completeness 0.30, validity 0.25, consistency 0.20, uniqueness 0.15,
timeliness 0.10, reconciliation **0.20** when present. Renormalise by `Σ(w)` (1.00 or 1.20).
API must return `dimensions_in_scope`, `dimensions_not_in_scope`, `weight_denominator`,
`scope_signature`. Never rank across different scopes without saying so.

### Patterns and suggestions

Patterns: concentration / lift across hour, DOW, contract, field, batch, **frequency**.
Lift is a ratio (how much more often a finding sits in one bucket than overall), not a count.

Suggestions: proposed changes (halt window, timezone, tick reference, …) with rationale and
`expected_effect`, **shown as text in v1**. Accept → mutate catalogue → re-run in the same
request is an extension (`POST /insights/suggestions/{id}/apply`). Finding override
(`POST /dq/findings/{id}/review`) is the same class of extension.

### Demo defects

Sample minute data is very clean. Demo strategy: lead with real findings (timezone trap,
settlement outside range, off-tick settlements), plus a **labelled** defect-injection utility
with a ground-truth manifest — never silently corrupt pristine samples.

---

## 10. Data model (summary)

Four DuckDB schemas:

| Schema | Role |
|---|---|
| `ref` | `contract`, `product`, `tick`, `session_calendar` |
| `stage` | `ingest_batch`, `market_record` (immutable), `record_reject` |
| `dq` | `dq_rule`, `dq_run`, `dq_finding`, `cleaning_action`, view `market_record_clean` |
| `mart` | `bar_daily` (with quality columns + `source_frequency`), `dq_metric_daily`, VWAP as view |

Absent by design in v1: users, roles, report catalogues, runtime third-party fetches.

Full DDL: `specs/data-model.md`.

---

## 11. API (summary)

Base path `/v1`. Synchronous writes return finished results. Conventions: UTC on the wire,
`basis=raw|clean`, `frequency=minute|daily`, trade dates in date filters, RFC 7807 errors.

| Area | Endpoints |
|---|---|
| Reference | `GET /health`, `/contracts`, `/calendar` |
| Ingest | `POST /preview`, `POST /batches` → 201, `GET` batches/rejects, `DELETE` purge |
| Analytics | `/analytics/bars/daily`, `/analytics/vwap`, `/analytics/compare` |
| DQ | `/dq/summary`, `/metrics`, `/findings`, rules, runs. **v1:** GET findings (read-only). `POST .../review` (override) is an extension |
| Insights | `/insights/patterns`, `/suggestions`. **v1:** GET only. `apply` / `dismiss` are extensions |

VWAP on daily-only contracts returns a structured frequency-unavailable error. Comparison
supports `compare=basis` (raw vs clean) and `compare=frequency` (supplied daily vs derived).

Full contract: `specs/api-contract.md`.

---

## 12. UI shape

Wireframes and tooltip copy: `specs/loupe-ui-design.md`. Journeys (historical, locked):
`_notes/founding/loupe-solution-design.md` (App Usage).

Shared chrome: sidebar (persona, trade dates, Load demo data, ingested-file list) +
**Summary** then **Specifics**. Selecting a Summary row drives Specifics. Specifics is
**Why / Impact / Address** first; charts sit under it only when that persona will look at
them. Address is suggestion **text** in v1 (no apply button).

| | Summary | Specifics |
|---|---|---|
| Risk | Worst-first; score, book hit (contracts needing attention), session completeness, settlement-quality sparkline; Status + Closing-day | Multi-select; Why / Impact / Address; daily OHLCV with quality on the candle; raw vs clean. No tick log |
| Trader | Name-sorted; Contracts + With warnings; Root, Contract, Score, Warning | One contract; window completeness; warnings; changelog **marks on the clean series** (click ↔ mark; raw ghost); OHLCV + VWAP or in-place “needs minute bars” |
| Analyst | Score then name; finding counts; top issue; both-frequency count when relevant | Read-only findings log; raw neighbourhood of selected finding; patterns (lift); suggestions as text; engine changelog; diagnostic charts + `REC.*` when both frequencies exist |

v1 UI ingest path: **Load demo data** posts local files to `POST /v1/ingest/batches` with
`origin=demo`. There is no file uploader, no confirm-upload, and no sidebar preview panel.
After a successful load the sidebar lists batches from `GET /v1/ingest/batches` (filename,
format, origin) — inventory of what was ingested, not a directory walk. Demo CSV rows
(`origin = demo` and CSV) are marked converted from Parquet, not as defects; injected CSV
is the synthetic disclosure, not that mark.

Capability preview is **UI-absent and API-only.** `POST /v1/ingest/preview` stays.
Unavailable capabilities are explained in place on the dashboard after load (disabled VWAP
with reason), not silently omitted and not via a pre-commit sidebar matrix.

Help on **named boxes** (KPI tiles and headers), one sentence, not every grid cell.
Skip Why / Impact / Address rows and the findings What column. Streamlit: `st.metric(..., help=...)`,
dataframe column `help`, chart caption.

### Demo priorities

1. **Raw vs clean overlay** (especially on daily / injected defects) — shows what cleaning buys.  
2. **Quality annotation on the candle** — trustworthiness at the point of use.  
3. **Timezone misalignment** as centrepiece finding when relevant.  
4. **Reconciliation** when both frequencies are loaded.

---

## 13. Testing strategy

| Tier | What | Where |
|---|---|---|
| Unit | One rule / helper / aggregation invariant per fixture | `tests/fixtures/*.csv` (committed) |
| Property | `low ≤ open,close ≤ high`; cleaning idempotent; parts sum to whole | pytest |
| Contract | FastAPI `TestClient` against OpenAPI shapes | `tests/api/` |
| Oracle | Minute→daily open/high/low vs vendor daily; boundary recovery | Real `data/samples/` (fetched, not committed) |
| Injection | Labelled synthetic defects with manifest | Derived from samples |
| UI | Persona view assembly; absence of apply/override controls | `streamlit.testing.v1.AppTest` over a stubbed API client, `tests/ui/` |
| Integration | Cold start, the real client against a real server, durability on disk | uvicorn on an ephemeral port over a file-backed store, `tests/integration/` |
| Stub parity | Every stubbed envelope's keys exist on the model it stands in for | `tests/ui/test_pages.py` |

Edge cases to fixture explicitly: exact dup, key conflict, mid-session gap, missing day,
negative volume, `high < low`, close outside range, unparseable timestamp, empty file,
Sunday-evening trade date, three-character root (`SR3`), off-tick settlement, timezone smear.

### A test that cannot fail is worse than no test

Three defects reached `main` behind green suites during slice 5, all the same shape: the test
exercised the path where the feature is **absent** and never the path where it works. Each
would have passed against a function that returned `None` unconditionally. Three rules follow,
and they are cheap:

**Assert the guard, not only the property.** An assertion inside `if` or `for` proves nothing
if the branch is never entered. A test that checks "every callout comes from the named set"
must also assert it saw a callout. Where a fixture produces none, say so and use one that does.

**Test both sides of a filter.** A selector needs an input it admits *and* an input it
rejects, asserted separately. One side alone cannot distinguish a working filter from one that
returns nothing — or everything.

**Build stubs from the response, not from the caller.** A fixture written to match the code
can only confirm the code's own assumptions. Copy a real response, and assert the stub's keys
against the model it stands in for (`tests/ui/test_pages.py` does this for every envelope);
unknown keys are mechanically detectable and were the whole of the third defect.

The residue these rules do not cover is a stub that *omits* a field the API sends, since
absence is legitimate. That is what a built-path test is for: assert the feature does its job
on data that should trigger it, not merely that it declines gracefully on data that should
not.

### Every tier stubs a seam, so one tier must stub none

The three defects above were caught by rules about assertions. The next three were not caught
at all, and reached a first run of the app: the store had no schema, the upload button did
nothing, and bars were missing until something rebuilt them. They share a cause that no
assertion rule reaches — **each tier simulates exactly the thing the others test**. `tests/api/`
runs HTTP in-process and is handed a database somebody already set up; `tests/ui/` drives the
pages over a client that never builds a request; every tier above runs `:memory:` and closes
with the test. The seams between them — an unbootstrapped store, a real multipart body on a
real socket, and state that has to outlive the request that wrote it — were the only places
left for a defect to hide, and that is where all three were.

`tests/integration/` therefore simulates neither side: uvicorn on a real port, a file-backed
DuckDB, and the same `LoupeClient` the pages use. It is deliberately small — seams only, since
behaviour belongs in the faster tiers that own it — and it earned its place immediately, by
finding that every read route answered a fresh store with a bare 500 and that the client threw
away the body of §4.3's duplicate-file refusal.

---

## 14. Extensibility and non-goals

**In scope to extend without rewriting:** new file layouts (column mapping), new roots/sessions
(seed `ref.product` / calendar), new rules (catalogue entry + runner + fixture, seeded into
`dq_rule`; workflow in `specs/dq-rules-and-scoring.md` §17), async ingest above size threshold,
RBAC as router dependency, AI narratives over aggregated pattern stats only, finding **override**,
suggestion **apply / dismiss** (mutate catalogue and re-run).

**Out of scope for v1:** live feeds, multi-user concurrency, continuous/back-adjusted series as a
product feature (name as top extension; `roll_date` already exists), runtime HuggingFace fetches,
full holiday calendars for every venue, AI that receives raw market data, interactive apply or
override from the UI.

---

## 15. Data flow (Trader, sync)

```
User                    Streamlit                     FastAPI                      DuckDB
 │                          │                            │                           │
 ├─ Select view=Trader ────►│                            │                           │
 │                          ├─ GET /dq/summary ─────────►│                           │
 │                          │  GET /analytics/...        ├─ query marts / views ────►│
 │                          │◄── JSON ───────────────────┤◄── aggregates ────────────┤
 │◄─ Trader dashboard ──────┤                            │                           │
 │                          │                            │                           │
 ├─ Load demo data ────────►│                            │                           │
 │                          ├─ POST /ingest/batches ────►│  load → rules → marts ───►│
 │                          │◄── 201 batch summary ──────┤                           │
 │                          ├─ GET /ingest/batches ─────►│                           │
 │◄─ Sidebar file list ─────┤◄── filename, format, origin┤                           │
 │◄─ Dashboard refresh ─────┤                            │                           │
 │                          │                            │                           │
 ├─ Change date filter ────►│  GET /analytics/...?start= │  re-query slice ─────────►│
 │◄─ Charts/metrics update ─┤◄── JSON ───────────────────┤                           │
 │   (changelog marks bind  │                            │                           │
 │    to the series)        │                            │                           │
```

---

## 16. Deliverables checklist

- [ ] Working app (venv and/or Docker)  
- [ ] README: philosophy, architecture, trade-offs, limitations, extensibility, walkthrough  
- [ ] Architecture overview (this doc + layer diagram in README)  
- [ ] UI: Summary / Specifics + persona selector + Load demo data + ingested-file list + named-box tooltips  
- [ ] Unit + integration tests; oracle test marked optional if samples absent  
- [ ] `tools/fetch_samples.py` + gitignore for `data/samples/` and `*.duckdb`  

---

## 17. Implementation order (suggested)

Done-when and file lists: `plans/`. Promote the matching research note into `specs/` as the first done-when of each slice.

1. `data` — DuckDB schema, ingest preview/load, reference seed from sample  
2. `quality` — core rule families + score; fixtures first  
3. `insights` — daily bars + VWAP; wire oracle test  
4. `api` — routes matching `specs/api-contract.md`  
5. `ui` — Summary/Specifics, persona selector, named-box tooltips  
6. Reconciliation + **report-only** suggestions + demo injection (apply/override later)  
7. Demo corpus — fetch, CSV conversion, Load demo data and Inject  
8. Ingest chrome — one sidebar ingest path; ingested-file list and CSV conversion mark  
9. README walkthrough against real `ESZ25` (or chosen volatile window)
