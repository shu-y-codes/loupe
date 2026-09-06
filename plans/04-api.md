# 04 — API

**Goal.** FastAPI `/v1` matching the promoted contract. Handlers call quality / insights /
data; no duplicated business maths.

**Status.** done — 2026-09-06

Amended 2026-09-06 after done-when 1: three prerequisites the promote surfaced (purge,
capability state, dependencies) and one scope cut (patterns / suggestions to slice 6).
See **Sequencing** below. Amended again the same day: done-when 9 closes the
`build_bars` gap left between slices 3 and 4.

## Done when

1. ✅ Promote `_notes/cursor/05-api-contract.md` → `specs/api-contract.md`. Note marked
   superseded. Do not code from the note.
2. ✅ Dependencies added and locked: `fastapi`, `python-multipart` (the multipart upload in
   §4 — FastAPI's `UploadFile` will not parse without it), and `httpx` in the dev group
   (`TestClient` is a thin wrapper over it). None of the three is in `pyproject.toml` or
   `uv.lock` today; every other done-when here is blocked on this one.
3. ✅ Base path `/v1`. Sync writes return finished results. UTC on the wire;
   `basis=raw|clean`; `frequency=minute|daily`; RFC 7807 errors.
4. ✅ Areas in the solution brief §11 exist, **less insights** (see 8): health/reference,
   ingest preview + batches (201, `file_hash` 409) + rejects + purge, analytics
   bars/VWAP/compare, DQ summary/metrics/findings (GET findings read-only), rules GET,
   runs POST/GET.
5. ✅ **Batch purge helper in `data`, not in the handler.** `DELETE /v1/ingest/batches/{id}`
   is v1 (contract §4) and `stage.ingest_batch.status` has carried `'purged'` since slice 1
   ([ddl.sql:76](src/loupe/data/ddl.sql#L76)), but nothing implements the cascade. One
   helper owns which tables a purge touches — `stage.market_record`, `stage.record_reject`,
   the batch's `dq.dq_finding` rows, and the `mart.bar_daily` rows derived from them — and
   the route calls it. A handler that spells out that table list is business logic in `api`.
   Deriving the mart rows to drop is the same span-overlap question slice 3 answered for
   `file`-scope findings ([03-insights.md](03-insights.md), spec corrections); reuse that
   resolver rather than writing a second one.
6. ✅ VWAP on daily-only returns a structured `CAP.FREQUENCY_UNAVAILABLE` error
   (contract §6, line 428).
7. ✅ **The capability check lives in `insights`, not in the handler.** Done-when 6 needs a
   state the gate does not yet expose: `PublishedSeries.unavailable`
   ([gate.py:202-205](src/loupe/insights/gate.py#L202-L205)) means *no rows and nothing
   blocking* — genuinely empty — which is not the same as *the contract holds daily records
   only, so a 15-minute VWAP cannot exist*. Those two render as different HTTP responses:
   an empty 200 and a 4xx `CAP.*` refusal. Add the fourth state alongside `rows` /
   `blocked` / `unavailable` and let `published_vwap` return it, for the reason slice 3
   introduced the type at all (done-when 9): collapsing distinguishable absences into "no
   data" is the failure it exists to prevent. A handler that queries which frequencies a
   contract holds has taken a capability decision away from the layer that owns publication.
8. ✅ OpenAPI is generated from the app; `TestClient` covers shapes.
9. ✅ **`build_bars` after assess (gap from slices 3/4).** Slice 3 shipped the mart writer;
   slice 4 shipped `GET /analytics/bars/daily` and ingest/`dq/runs`, but nothing called
   `insights.build_bars` on those write paths — the UI showed "No bars in this window"
   after a successful upload. `POST /ingest/batches` materialises bars for the batch's
   contracts (after assess when `validate=true`, after load when `validate=false`);
   `POST /dq/runs` rebuilds for the same contract scope as the run. Handlers call
   `insights`; do not fold this into `quality.assess`. Two-pass assess for
   `CON.DERIVED_BAR_INVALID` stays out of scope (that rule still needs a later re-run).

## Sequencing — insights routes move to slice 6

`GET /v1/insights/patterns` and `/v1/insights/suggestions` are v1 in the contract (§7) and
stay v1. They are **not built in this slice**: nothing backs them. Patterns and suggestions
are slice 6 by an explicit decision already recorded in code
([quality/__init__.py:12](src/loupe/quality/__init__.py#L12)), and slice 6 runs after this
one. With no layer to call, the only way to ship the two routes here is to put lift and
rationale maths in a handler — the one thing this slice's goal forbids.

So the two GET routes land in [06-rec-suggestions-demo.md](06-rec-suggestions-demo.md),
in the same slice as the reports they serve. This slice ships the `/v1/insights` router
empty of them; slice 6 adds two handlers and their contract tests to the app built here.
The contract is unchanged — this is build order, not scope.

## Files created

- `src/loupe/api/` — `app` (factory and the error-handler registry), `deps` (the single
  connection and the shared query parameters), `errors` (RFC 7807), `models` (envelopes),
  and `routes/` — `reference`, `ingest`, `analytics`, `dq`, and `insights` (mounted, empty
  until slice 6).
- `src/loupe/data/purge.py` — the cascade, with `BatchNotFound` / `BatchAlreadyPurged`.
- `tests/api/` (47), `tests/data/test_purge.py` (7), `tests/insights/test_capability.py` (7).

Edited: `pyproject.toml` and `uv.lock` (done-when 2); `src/loupe/insights/gate.py` and
`vwap.py` (the capability state, done-when 7); `src/loupe/data/__init__.py` and
`src/loupe/insights/__init__.py` (exports). `tests/insights/test_vwap.py` — see below.

v1: no `POST .../review`, no suggestion apply/dismiss, no `POST`/`PATCH /dq/rules`
(extensions). No patterns/suggestions routes — slice 6, above.

## Tests

Happy-path ingest 201; duplicate hash 409; findings GET is read-only; VWAP refused
in place for daily-only with `CAP.FREQUENCY_UNAVAILABLE`, and distinguishably from an
empty series and from a `critical`-blocked one (the three-way distinction slice 3 built);
purge removes the batch's staged, reject, finding and derived-mart rows and leaves an
unrelated batch intact; RFC 7807 on validation errors.

## Measured: what the build changed under the plan

**Two deviations, both because a foreign key already answered the question.**

Done-when 5 anticipated reusing `insights.gate`'s span-overlap resolver to decide which mart
rows a purge drops. It is not needed and would be less precise. That resolver exists because
`dq.dq_finding` carries no `batch_id` and cannot say which upload produced it;
`stage.market_record` carries `batch_id` *and* `trade_date`, so "which sessions did this
batch feed" is a `GROUP BY`, not an inference from timestamp spans. `dq.dq_run.batch_id`
answers the same question for findings. `insights` also sits above `data` in the layering
(§6), so importing it there would invert the dependency. Recorded in `data/purge.py`.

Purge therefore deletes findings it can attribute — from a run scoped to the batch, or
pinned to one of its records — and leaves session-scope findings from a corpus-wide run
alone, because that session may hold another batch's records and the finding is a statement
about all of them. Re-validating (`POST /v1/dq/runs`) is the honest response to a changed
corpus; guessing which half of a statement to delete is not.

**One slice-3 test changed rather than added to.**
`tests/insights/test_vwap.py::test_a_daily_only_corpus_yields_no_line_at_all` asserted
`series.unavailable` for a daily-only contract. Done-when 7 is the decision that this answer
was wrong — that case is a refusal, not an empty result — so the test now asserts
`frequency_unavailable` and, explicitly, `not unavailable`. It is renamed
`test_a_daily_only_corpus_is_refused_rather_than_empty` and carries the reason. No other
existing test needed changing: `unsupported` defaults to `None`, so every other caller of
`PublishedSeries` behaves exactly as before.

**Suite:** 375 passed (353 plus 22 corpus-gated), ruff clean.

## Attach

- `specs/loupe-solution-design.md` §11
- `specs/api-contract.md`

## Non-goals

Streamlit, apply/override, async job table, auth/RBAC. Pattern and suggestion maths
(slice 6) — including their two routes.
