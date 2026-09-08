# Loupe — Solution Design

Refined design for the Market Data Quality & Analytics exercise.

Revised 2026-09-08: two pages — Review (one contract) and Overview (corpus family tiles);
locked decision 6 keeps no-auth and drops “one reviewer page” as a persona ban. Same day:
§12 makes grain/source, selected-family issues, pattern evidence and
chart identity explicit; §17 inserts slice 11 and moves the README walkthrough to 12.
Revised 2026-09-07: reviewer chrome — cards are the family selector, no score
caption, OHLCV legend + zoom, grouped sidebar. Same day: one reviewer page — four family
cards and two charts; personas are not a view selector (slice 9). Same day: v1 UI ingest is
Load demo data; capability preview is API-only and disclosed in place (slice 8).
Revised 2026-09-06: `specs/api-contract.md` promoted (slice 4 done-when 1).
Revised 2026-09-05: `specs/analytics-semantics.md` promoted (slice 3 done-when 1).
`specs/dq-rules-and-scoring.md` promoted (slice 2). Slice 1 specs (`data-model.md`,
`sample-corpus.md`) already promoted.

This document is the implementation brief. **`specs/` is normative.** Calculation, schema,
rule catalogues, API payloads, and UI belong in `specs/` (this brief plus sibling specs).
`_notes/` is a research scrapbook and is not implementation law. `_notes/founding/` is a
locked historical record. Where a spec and a note disagree, the spec wins. If a topic is
still only documented under `_notes/cursor/`, promote it into `specs/` before treating it
as binding. Execution sequence: `plans/`.

| Detail | Document |
|---|---|
| Reviewer page (cards, overlay, charts, tooltips) | `specs/loupe-ui-design.md` |
| Overview page (corpus family tiles) | `specs/loupe-ui-design.md` (Overview) |
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

## 2. What the page answers

No authentication in v1. RBAC is a documented extension that filters contract scope without
changing endpoint signatures. The UI is **two pages**, not a persona selector: **Review**
(one contract, four cards and two charts) and **Overview** (loaded contracts × grain,
family-tile table). Default landing is Review.

| Product question (§1) | What the page shows |
|---|---|
| **Can I trust this data?** | Four named checks (gaps, duplicates, invalid values, recurring patterns) for one selected contract × date window. The four cards *are* the selector. Aggregated issues: What / Days / Records / What we did. Report-only: no apply or override. The page does not draw a score. |
| **What does this data look like?** | Daily OHLCV then rolling 15-minute VWAP, full width, marks for the **selected family** (not `max_severity`) with an OHLCV legend. Picture of that family below VWAP. Daily-only keeps the VWAP panel and says “needs minute bars”. |

Illustrative question — *"I want to backtest ES through a wild market. How clean is this
data?"* — remains valid. The shipped sample runs **2021–2026**, so demos use a volatile window
inside that range rather than 2008. Chrome, overlay grammar, and empty states:
`specs/loupe-ui-design.md`.

### Advise loading both grains

Loupe accepts whichever grain arrives. A minute-only contract still gets derived daily bars,
VWAP, gap and duplicate checks, and a changelog. A daily-only contract still gets settlement
OHLCV, invalid-value checks, and in-place refusal of VWAP. Nothing is a prerequisite, and no
upload is refused for arriving alone.

**Reconciliation still needs two files.** A daily file can only be checked against itself:
close inside the bar range, on the tick, not duplicated, session present. Nothing in that set
can catch a settlement file that is internally perfect and still wrong. Only `REC.*` can
(§9), and only when the minute tape is there to compare against. That advice is about the
measurement, not about a Risk view: load the minute tape alongside the daily file for the
contracts you care about so the score can include it.

The failure is silent if the page does not say so. A **daily-only** contract still fills the
four cards and the daily chart, the score still computes on the API envelope, reconciliation
is out of scope, and §11.3 renormalises the denominator from 1.20 to 1.00. The reviewer page
does not draw that number.

**One grain scores what a file says about itself; two grains score whether it is true.** Where
a contract holds one, every surface that **shows a score** must say which dimensions were in
scope (`specs/dq-rules-and-scoring.md` §11.3), and the missing companion grain is named as
advice — on `POST /v1/ingest/preview` for API callers. The reviewer page does not show a
score; daily-only VWAP says “needs minute bars”. Never as a gate. The v1 UI does not host a
pre-commit preview panel.

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
6. **No authentication.** Two pages, still not a persona selector: **Review** (one contract)
   and **Overview** (corpus family tiles). Neither page is role-shaped.
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
the VWAP panel and says "needs minute bars". There is no sidebar capability matrix before
commit.

| Uploaded | Daily OHLCV | Rolling 15-min VWAP | Reconciliation (`REC.*`) |
|---|---|---|---|
| Minute only | Derived | Yes | No |
| Daily only | Ingested as-is | Unavailable (structured refusal, not empty chart) | No |
| Both | Derived **and** compared | Yes | Yes |

Do not invent a 15-*day* VWAP from daily bars and label it as the exercise requirement.

**Why accept daily.** Every naturally occurring defect in the sample lives in the daily files;
the minute tape is essentially clean. Settlement quality lives in the daily files.
Rejecting daily would also make user-supplied reconciliation impossible and force a runtime
HuggingFace dependency — which we reject.

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
- **Name the companion grain** (§2, "Advise loading both grains"):
  a daily file with no minute tape for that contract cannot be reconciled. Neither file is
  refused and neither is incomplete on its own terms. The API preview says what the second
  file would add; the v1 UI says the same in place after load by keeping the VWAP panel
  with “needs minute bars”. It does not draw a score caption.

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

Wireframes, overlay grammar, and tooltip copy: `specs/loupe-ui-design.md`. Journeys
(historical, locked): `_notes/founding/loupe-solution-design.md` (App Usage).

**Two pages.** Sidebar: Review | Overview switch (default Review). Shared: Load demo data,
ingested files grouped by contract coverage (Daily + minute / Daily-only / Minute-only). No
persona radio.

**Review.** Contract picker, explicit Quality grain for dual-grain contracts
(Minute default; single-grain is quiet context), trade dates. Main
column, in this order: four family cards (Gaps, Duplicates, Invalid values, Recurring
patterns) — the cards *are* the family selector, no Check control and no score caption;
Daily OHLCV then 15-minute VWAP, full width, **selected-grain and selected-family** marks
(not `max_severity`) with an OHLCV legend, independent pan/zoom (shared x across OHLCV +
volume); picture of the selected family **below** VWAP; selected-family aggregated issues
(What / Days / Records / What we did). Report-only:
no apply or override.

**Overview.** Corpus scan: one row per loaded contract × held grain; columns are the four
family tiles plus Grain; full held window. No contract picker, Quality grain, or dates.
Selecting a row opens Review on that contract and grain. Chrome: `specs/loupe-ui-design.md`.

Invariants the chrome must keep:

- Cards *are* the selector. Clicking a card selects the overlay and the picture. Zero on a
  card means the check ran. Help on the count, not the family name.
- Cards, patterns, issues, overlay, picture and OHLCV use one explicit Quality grain and
  source: Minute → derived bars; Daily → supplied vendor bars. Changing family keeps grain.
- Invalid evidence names its actual subject field and carries the finding grain/source.
- Pattern picture prose and chart are one `(rule_id, dimension)` group with exposure shares,
  lift, support and days supplied by the API.
- No score caption on this page (`score` / `scope_signature` may still arrive on
  `GET /v1/dq/checks`).
- A gap can mark an absent day with **no** bar row. Never a zero-filled settlement candle.
- Minute `CMP.MISSING_TIMESTAMP` can mark a derived daily session.
- `OUT.*` stays off the strip. Rule IDs are captions, not headlines.
- Daily-only keeps the VWAP panel and says “needs minute bars”.
- OHLCV marks are a legend, not a caption. Daily OHLCV and the volume pane pan/zoom on a
  shared x; VWAP zooms independently; double-click resets both. Contract, grain, or date
  scope changes reset chart identity to the returned extent; family-only changes preserve it.
- VWAP remains minute. Daily Quality grain on a dual-grain contract labels it context-only
  and suppresses daily-family marks; daily-only still says “needs minute bars”.
- Ingested files group by contract coverage. Planted defects group by strip family, with
  **Other (off the strip)** for injectable rules that are not on the four cards.
- Widgets call HTTP only. They do not group `findings[]` to build cards or overlay marks.

v1 UI ingest path: **Load demo data** posts local files to `POST /v1/ingest/batches` with
`origin=demo`. There is no file uploader, no confirm-upload, and no sidebar preview panel.
After a successful load the sidebar lists batches from `GET /v1/ingest/batches` grouped by
contract coverage using `GET /v1/contracts` (Daily + minute / Daily-only / Minute-only).
Demo CSV rows (`origin = demo` and CSV) are marked converted from Parquet, not as defects;
injected CSV is the synthetic disclosure, not that mark.

Capability preview is **UI-absent and API-only.** `POST /v1/ingest/preview` stays.
Unavailable capabilities are explained in place on the dashboard after load (disabled VWAP
with reason), not silently omitted and not via a pre-commit sidebar matrix.

Help on **named boxes** (family-card counts, headers), one sentence, not every grid cell.
Skip aggregated-issue What cells and picture sentences. Streamlit: `st.metric(..., help=...)`
on the count, dataframe column `help`. Overlay marks are a chart legend.

### Demo priorities

1. **Selected-family overlay** on Daily OHLCV — the four checks, not worst-severity paint.
2. **Absent settlement as a dashed column** — never a zero-filled bar.
3. **Timezone misalignment** as centrepiece finding when relevant.
4. **Daily-only VWAP in place** with “needs minute bars” — not a score caption.

---

## 13. Testing strategy

| Tier | What | Where |
|---|---|---|
| Unit | One rule / helper / aggregation invariant per fixture | `tests/fixtures/*.csv` (committed) |
| Property | `low ≤ open,close ≤ high`; cleaning idempotent; parts sum to whole | pytest |
| Contract | FastAPI `TestClient` against OpenAPI shapes | `tests/api/` |
| Oracle | Minute→daily open/high/low vs vendor daily; boundary recovery | Real `data/samples/` (fetched, not committed) |
| Injection | Labelled synthetic defects with manifest | Derived from samples |
| UI | Two-page assembly (Review + Overview, no persona switch); family overlay vs caption; VWAP in-place refusal; absence of apply/override | `streamlit.testing.v1.AppTest` over a stubbed API client, `tests/ui/` |
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

## 15. Data flow (reviewer page, sync)

```
User                    Streamlit                     FastAPI                      DuckDB
 │                          │                            │                           │
 ├─ Pick contract + dates ─►│                            │                           │
 │                          ├─ GET /dq/checks ──────────►│                           │
 │                          │  GET /analytics/bars,vwap  ├─ query marts / views ────►│
 │                          │◄── JSON ───────────────────┤◄── aggregates ────────────┤
 │◄─ Cards, charts, picture ┤                            │                           │
 │                          │                            │                           │
 ├─ Select family ─────────►│  GET /dq/checks?family=    │  overlay marks ──────────►│
 │◄─ Overlay + picture ─────┤◄── JSON ───────────────────┤                           │
 │                          │                            │                           │
 ├─ Load demo data ────────►│                            │                           │
 │                          ├─ POST /ingest/batches ────►│  load → rules → marts ───►│
 │                          │◄── 201 batch summary ──────┤                           │
 │                          ├─ GET /ingest/batches ─────►│                           │
 │◄─ Sidebar file list ─────┤◄── filename, format, origin┤                           │
 │◄─ Dashboard refresh ─────┤                            │                           │
 │                          │                            │                           │
 ├─ Change date filter ────►│  GET /dq/checks?start=     │  re-query slice ─────────►│
 │◄─ Cards/charts update ───┤◄── JSON ───────────────────┤                           │
```

Overview does not call bars or VWAP. It lists `GET /v1/contracts`, then one
`GET /v1/dq/checks?contract=&frequency=` per held grain. The widget does not group
`findings[]`. Selecting a row sets Review's contract and Quality grain.

---

## 16. Deliverables checklist

- [ ] Working app (venv and/or Docker)  
- [ ] README: philosophy, architecture, trade-offs, limitations, extensibility, walkthrough  
- [ ] Architecture overview (this doc + layer diagram in README)  
- [ ] UI: Review (four cards *are* the selector, family overlay with legend,
      zoomable OHLCV + volume, picture below VWAP, no score caption) + Overview
      (corpus family tiles, click-through to Review) + Load demo data +
      ingested files grouped by coverage + planted defects grouped by family + named-box
      tooltips on counts
- [ ] Unit + integration tests; oracle test marked optional if samples absent  
- [ ] `tools/fetch_samples.py` + gitignore for `data/samples/` and `*.duckdb`  

---

## 17. Implementation order (suggested)

Done-when and file lists: `plans/`. Promote the matching research note into `specs/` as the first done-when of each slice.

1. `data` — DuckDB schema, ingest preview/load, reference seed from sample  
2. `quality` — core rule families + score; fixtures first  
3. `insights` — daily bars + VWAP; wire oracle test  
4. `api` — routes matching `specs/api-contract.md`  
5. `ui` — first chrome (slice 5); later rebuilt as the one reviewer page (slice 9)
6. Reconciliation + **report-only** suggestions + demo injection (apply/override later)
7. Demo corpus — fetch, CSV conversion, Load demo data and Inject
8. Ingest chrome — one sidebar ingest path; ingested-file list and CSV conversion mark
9. Reviewer-facing UI — four family cards, selected-family overlay, picture below VWAP
10. Reviewer chrome after click-test — cards as the family control, no score line, zoom + legend, grouped sidebar (`plans/10-reviewer-chrome.md`)
11. Grain-honest review — explicit quality frequency, source-aligned evidence, honest Invalid/pattern pictures, VWAP zoom (`plans/11-grain-honest-review.md`)
12. README walkthrough against real `ESZ25` (or chosen volatile window), describing Review after slice 11 and the Overview switch if slice 13 has shipped
13. Overview page — corpus family-tile table, Review main column unchanged (`plans/13-overview-page.md`)
