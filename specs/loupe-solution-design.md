# Loupe — Solution Design

Refined design for the Market Data Quality & Analytics exercise.

This document is the implementation brief. Detailed semantics, schema DDL, rule catalogues
and API payloads live under `_notes/cursor/`; where that corpus and this brief disagree, this
brief wins on scope and priority, and the numbered notes win on factual claims about the sample
data and on calculation correctness.

| Detail | Document |
|---|---|
| Futures domain (symbology, sessions, rolls, ticks) | `_notes/cursor/01-futures-data-primer.md` |
| Daily bars, VWAP, expected grid | `_notes/cursor/02-analytics-semantics.md` |
| DuckDB schema | `_notes/cursor/03-data-model.md` |
| DQ rules, score, patterns, suggestions, `REC.*` | `_notes/cursor/04-dq-rules-and-scoring.md` |
| FastAPI contract | `_notes/cursor/05-api-contract.md` |
| Sample corpus facts and oracle measurements | `_notes/cursor/06-sample-data.md` |
| Persona UI, Summary / Specifics, wireframes, tooltips | `specs/loupe-ui-design.md` |
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

Upload preview discloses what the file unlocks before commit.

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

- Preview first: headers, types, inferred timezone / interval / frequency, capability matrix
- Sync `POST /v1/ingest/batches` → **201** with finished summary (`dq_run_id`, row counts, elapsed)
- Idempotent on `file_hash` (409 if duplicate)
- Parse failures → `stage.record_reject`; nulls and soft defects → load + find
- Frequency discriminator on every record: `(contract_id, frequency, ts_utc)` — loading daily and
  minute without it collides

### Oracle (test asset, not runtime)

Vendor daily vs minute-derived daily: **open / high / low** agree on ~96.5% of complete sessions.
Close is settlement (not last trade); volume on the tape is ~95% of reported daily. Use the
oracle to **test** an independently chosen definition — never to derive one. Claim: "agrees with
vendor daily bars," not "verified correct."

---

## 8. Analytics semantics (summary)

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

Full DDL: `_notes/cursor/03-data-model.md`.

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

Full contract: `_notes/cursor/05-api-contract.md`.

---

## 12. UI shape

Wireframes and tooltip copy: `specs/loupe-ui-design.md`. Journeys (historical, locked):
`_notes/founding/loupe-solution-design.md` (App Usage).

Shared chrome: sidebar (persona, trade dates, upload) + **Summary** then **Specifics**.
Selecting a Summary row drives Specifics. Specifics is **Why / Impact / Address** first;
charts sit under it only when that persona will look at them. Address is suggestion **text**
in v1 (no apply button).

| | Summary | Specifics |
|---|---|---|
| Risk | Worst-first; score, book hit (contracts needing attention), session completeness, settlement-quality sparkline; Status + Closing-day | Multi-select; Why / Impact / Address; daily OHLCV with quality on the candle; raw vs clean. No tick log |
| Trader | Name-sorted; Contracts + With warnings; Root, Contract, Score, Warning | One contract; window completeness; warnings; changelog **marks on the clean series** (click ↔ mark; raw ghost); OHLCV + VWAP or in-place “needs minute bars” |
| Analyst | Score then name; finding counts; top issue; both-frequency count when relevant | Read-only findings log; raw neighbourhood of selected finding; patterns (lift); suggestions as text; engine changelog; diagnostic charts + `REC.*` when both frequencies exist |

Upload flow: file → **preview / capability disclosure** → confirm → sync progress → dashboard
updates on return. Unavailable capabilities are explained in place (disabled VWAP with reason),
not silently omitted.

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

Edge cases to fixture explicitly: exact dup, key conflict, mid-session gap, missing day,
negative volume, `high < low`, close outside range, unparseable timestamp, empty file,
Sunday-evening trade date, three-character root (`SR3`), off-tick settlement, timezone smear.

---

## 14. Extensibility and non-goals

**In scope to extend without rewriting:** new file layouts (column mapping), new roots/sessions
(seed `ref.product` / calendar), new rules (rows in `dq_rule`), async ingest above size threshold,
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
 ├─ Upload + preview ──────►│                            │                           │
 │                          ├─ POST /ingest/preview ────►│  infer freq/tz/interval   │
 │◄─ Capability matrix ─────┤◄── enables / disables ─────┤                           │
 ├─ Confirm upload ────────►│                            │                           │
 │                          ├─ POST /ingest/batches ────►│  load → rules → marts ───►│
 │                          │◄── 201 batch summary ──────┤                           │
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
- [ ] UI: Summary / Specifics + persona selector + capability-aware upload + named-box tooltips  
- [ ] Unit + integration tests; oracle test marked optional if samples absent  
- [ ] `tools/fetch_samples.py` + gitignore for `data/samples/` and `*.duckdb`  

---

## 17. Implementation order (suggested)

1. `data` — DuckDB schema, ingest preview/load, reference seed from sample  
2. `quality` — core rule families + score; fixtures first  
3. `insights` — daily bars + VWAP; wire oracle test  
4. `api` — routes matching `_notes/cursor/05-api-contract.md`  
5. `ui` — Summary/Specifics, persona selector, upload with capability disclosure, tooltips  
6. Reconciliation + **report-only** suggestions + demo injection (apply/override later)  
7. README walkthrough against real `ESZ25` (or chosen volatile window)
