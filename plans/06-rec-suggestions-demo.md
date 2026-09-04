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
4. Labelled injection utility + manifest — never silently corrupt pristine samples.
   Lead demos with real findings plus injected daily defects.

## Files to create

- `quality/` — `REC.*` runners, pattern/suggestion reports (extend slice 2)
- Injection helper + manifest (derived from samples, not committed vendor files)
- Tests for `REC.*`, lift, suggestion payload shape, injection labels

## Tests

`REC.*` skipped/empty when only one frequency; volume shortfall one direction;
injection rows labelled and listed in the manifest; suggestions have no apply path.

## Attach

- `specs/loupe-solution-design.md` §9 (reconciliation, patterns, demo defects)
- `specs/loupe-ui-design.md` (Analyst specifics; report-only)
- `specs/dq-rules-and-scoring.md` (incl. `REC.*`, patterns, suggestions)
- `specs/sample-corpus.md`

## Non-goals

Apply suggestion → mutate `dq_rule` / calendar → re-run. Finding override. AI
narratives. Those stay extensions (solution brief §14).
