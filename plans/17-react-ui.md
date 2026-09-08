# 17 — React reviewer UI

**Goal.** Replace the Streamlit reviewer UI with a Vite + React + TypeScript SPA that keeps
every current Overview / Review behaviour, adopts the canvases' editorial visual language,
and moves demo load / inject off the UI process onto FastAPI. Specs, primers and agent rules
are patched in the same slice.

**Status.** done — 2026-09-08

Written 2026-09-08. Do not reopen done UI slices (5, 8–10, 13–16); their product rules already
live in `specs/loupe-ui-design.md` and React implements that spec. Pending
[11-grain-honest-review.md](11-grain-honest-review.md) is Streamlit-era and is superseded by
this slice for implementation; its rules are spec text and are implemented here. Pending
[12-readme-walkthrough.md](12-readme-walkthrough.md) waits on this slice's README, then
describes the React walkthrough.

## What stays true

- Two destinations: **Overview** (default) and **Review**. Same sidebar split as today.
- HTTP-only widgets. No SQL, no rule grouping of `findings[]`, no bar or VWAP maths in the
  client.
- Report-only: no apply / override / dismiss / file uploader / persona selector / score line.
- Same envelopes: `GET /v1/health`, `/contracts`, `/dq/checks`, `/analytics/bars/daily`,
  `/analytics/vwap`, `/ingest/batches`, plus ingest POST/DELETE and `POST /v1/dq/runs`.
- Overlay keyed on **selected family**, never `max_severity`. Marks join bars by `trade_date`.
- The layer table in `specs/loupe-solution-design.md` §6 still forbids quality or insight
  maths in UI code.

## Visual source

The canvases are a style, not a runtime. `cursor/canvas` is not a dependency.

- `chart-issue-overlay.canvas.tsx` — family cards as a selectable grid; custom SVG candles,
  volume and VWAP; family marks (triangle, dashed **absent**, pin, paint, pattern band, VWAP
  break crosses); Pills, Stats, Callouts. Severity paint is not the lead grammar.
- `contract-family-tiles.canvas.tsx` — compact table typography, Grain as a pill, stacked
  Contract cell (`id` + `root · exchange`), live counts primary and zero counts tertiary.

Forbidden (canvas slop rules): gradients, box-shadows, emoji status, rainbow colour, giant KPI
type. Streamlit's `⚠️` becomes a warning **Callout**.

**Out of scope from the Overview canvas:** the by-root bar chart, the "noise first" sort, and
the sessions / records / hit Stats. Those were demo-cull research. Overview columns stay
Contract, Grain and the four `count unit` headlines ([15-overview-headlines.md](15-overview-headlines.md)).

## Architecture

Vite + React + TypeScript in `web/`.

- **Development:** two processes. Vite serves the app and proxies `/v1` to
  `http://127.0.0.1:8000`, so the client calls relative paths and no CORS policy exists.
- **Production:** one process. `loupe.api.app._mount_web` serves `web/dist` at `/` beside the
  API at `/v1`. Absent `web/dist` it is a no-op, so an unbuilt checkout still serves the API.

**The Python client moved.** `src/loupe/ui/client.py` → `src/loupe/client.py`. It is the
integration-test seam and no longer belongs to any page; React has its own
`web/src/api/client.ts`. `npm run types` pulls `/v1/openapi.json` into `src/api/schema.json`
(+ `schema.ts`), and `src/api/schema.test.ts` fails if a test stub invents a field.

**Demo left the UI process.** `prepare_demo_corpus` / `prepare_injection` read the filesystem,
write derived files and fetch from Hugging Face; a browser can do none of that. New v1 routes
call the existing `loupe.demo` helpers server-side and stream NDJSON progress. They are chrome
for locked decision 9, not a second ingest pipeline: every file goes through
`routes.ingest.ingest_path`, the same loader `POST /v1/ingest/batches` uses. Fetch still
happens only on an explicit press, and ingest still contacts no network.

Locked decision 7 stays **synchronous**. The rewritten rationale is single-user local DuckDB at
sample scale — not "Streamlit has no push". Demo progress is UI telemetry, not a job table:
nothing is persisted, no handle is returned, and the `done` event is the result.

## Done when

1. React reproduces every surface above against a live store. ✅
2. Overlay grammar matches the chart canvas; absent is a dashed labelled column, never a zero
   bar. ✅
3. Overview matches Streamlit's content with canvas table / pill styling. ✅
4. Demo load / inject / remove work from the browser via the new routes; filesystem and Hugging
   Face stay on the API. ✅
5. The `AppTest` suite is replaced by Vitest + Testing Library; stub parity still guards
   invented keys. ✅
6. Specs, primers and rules no longer teach Streamlit as the v1 UI. ✅

## What the live pass found

Three defects that only a real store surfaced, each now covered by a test.

**The inject / remove round trip was never reversible.** Purge is a soft delete, so the purged
batch keeps its `file_hash` and re-ingesting those bytes is refused as a duplicate — of a batch
holding no records. The Streamlit panel swallowed that 409 as "already there is the outcome we
wanted" and reported "Removed and the clean file restored" having restored nothing. Fixed with
`loupe.data.forget_batch`, used only by the demo swap; `DELETE /v1/ingest/batches/{id}` still
soft-deletes, and `tests/api/test_purge_route.py`'s documented trade-off is unchanged.

**`Math.max(...points)` is a crash at real size.** `/v1/analytics/vwap` for ESZ25 returns
**114,477** points; spreading that into a call is `RangeError: Maximum call stack size
exceeded`, and the page died before drawing. `charts/scale.ts` now has `extremes` (one pass)
and `bucketSeries` (at most one mark per pane unit — a selection, never an average, and a
bucket holding any null stays a break).

**Two scopes could share one screen.** Selecting a new contract left the old one's cards and
candles under a header naming the new one, and a card click moved the picture's heading before
its payload arrived. Envelope-derived content now reads the envelope's own `overlay.family`,
and the Review column blanks when the scope changes (but not when only the family does, which
would drop the zoom the spec says a family change preserves).

## Spec and doc patches (same slice)

Normative, amended in place with a one-line revision at the top:

- `specs/loupe-solution-design.md` — §3.7, §6 diagram and stack table, §12, §13 UI tier, §15
  sequence, §17 item 17.
- `specs/loupe-ui-design.md` — React component names for Streamlit widget names; tooltips are
  native `title` / accessible description; charts are the SVG overlay grammar; synthetic
  disclosure is a Callout.
- `specs/api-contract.md` — demo routes in §4 and the v1 route table; §4.4 rationale; the
  same-origin SPA note.
- `specs/analytics-semantics.md` — "no SQL in Streamlit" → "no SQL in the UI client".

Primers and README (docs-on-commit): `README.md`, `docs/how-loupe-works.md`,
`docs/how-tests-work.md`, `docs/clg26-data-journey.md`, `docs/README.md`,
`docs/metrics-primer.md`.

Agent rules: `.cursor/rules/loupe-project.mdc`,
`.cursor/rules/react-fastapi-duckdb.mdc` (renamed from `streamlit-fastapi-duckdb.mdc`),
`.cursor/rules/opus-token-discipline.mdc`. `_notes/founding/` is not edited.

No change to DQ formulae, sample-corpus claims, or data-model DDL.

## Files

- `plans/17-react-ui.md`, `plans/README.md`
- `specs/loupe-solution-design.md`, `specs/loupe-ui-design.md`, `specs/api-contract.md`,
  `specs/analytics-semantics.md`
- `src/loupe/client.py` (moved), `src/loupe/ui/` (deleted)
- `src/loupe/api/routes/demo.py`, `src/loupe/api/routes/ingest.py`, `src/loupe/api/models.py`,
  `src/loupe/api/app.py`, `src/loupe/api/deps.py`
- `src/loupe/data/purge.py`, `src/loupe/data/__init__.py`
- `web/` (new)
- `tests/api/test_demo_routes.py`, `tests/api/test_openapi.py`, `tests/data/test_purge.py`,
  `tests/integration/conftest.py`, `tests/integration/test_walkthrough.py`, `tests/ui/`
  (deleted)
- `pyproject.toml`, `README.md`, `docs/`, `.cursor/rules/`
