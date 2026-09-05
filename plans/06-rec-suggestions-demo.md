# 06 — Reconciliation, suggestions, demo

**Goal.** `REC.*` when both frequencies exist; report-only suggestions; labelled
defect injection with a ground-truth manifest.

**Status.** pending

## Done when

1. ✅ `REC.*` / pattern / suggestion shapes already live in `specs/dq-rules-and-scoring.md`
   (slice 2 promote). No further promote from `_notes/cursor/04-dq-rules-and-scoring.md`.
2. Reconciliation findings only when daily + minute exist for the same contract
   (OHLC disagreement coverage-gated, volume shortfall, session only-in-one,
   close-convention info). Score includes reconciliation when in scope.
3. Patterns (lift) and suggestions with rationale / `expected_effect`, shown as text.
   No apply/dismiss; no finding override.
4. **The two v1 insights routes, deferred here from slice 4.** `GET /v1/insights/patterns`
   and `GET /v1/insights/suggestions` are v1 in `specs/api-contract.md` §7 and were held
   back from [04-api.md](04-api.md) because nothing backed them — done-when 3 is the layer
   they call. Two handlers and their contract tests added to the app slice 4 built, in
   `src/loupe/api/` and `tests/api/`, calling the reports above; no lift or rationale maths
   in a handler. `min_lift` / `min_support` filter the pattern list; suggestions are
   report-only text and carry no apply path.
5. Labelled injection utility + manifest — never silently corrupt pristine samples.
   Lead demos with real findings plus injected daily defects.

## Files to create

- `quality/` — `REC.*` runners, pattern/suggestion reports (extend slice 2)
- Injection helper + manifest (derived from samples, not committed vendor files)
- Tests for `REC.*`, lift, suggestion payload shape, injection labels

Edited: `src/loupe/api/` and `tests/api/` — the two routes from done-when 4.

## Tests

`REC.*` skipped/empty when only one frequency; volume shortfall one direction;
injection rows labelled and listed in the manifest; suggestions have no apply path.
Both routes return their contract shape; `min_lift` / `min_support` filter; the
suggestions payload exposes no apply or dismiss link.

## Attach

- `specs/loupe-solution-design.md` §9 (reconciliation, patterns, demo defects)
- `specs/api-contract.md` §7 (the two routes)
- `specs/loupe-ui-design.md` (Analyst specifics; report-only)
- `specs/dq-rules-and-scoring.md` (incl. `REC.*`, patterns, suggestions)
- `specs/sample-corpus.md`

## Non-goals

Apply suggestion → mutate `dq_rule` / calendar → re-run. Finding override. AI
narratives. Those stay extensions (solution brief §14).
