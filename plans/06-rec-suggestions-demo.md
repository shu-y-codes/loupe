# 06 — Reconciliation, suggestions, demo

**Goal.** `REC.*` when both frequencies exist; report-only suggestions; labelled
defect injection with a ground-truth manifest.

**Status.** pending

## Done when

1. If `REC.*` / suggestion shapes are not already in `specs/dq-rules-and-scoring.md`,
   promote the remaining pieces from `_notes/cursor/04-dq-rules-and-scoring.md` (and
   sample claims from `06` if injection/oracle details are still only in the note).
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
- After promote: `specs/dq-rules-and-scoring.md`, `specs/sample-corpus.md`
- Research until promoted: `_notes/cursor/04-dq-rules-and-scoring.md`,
  `_notes/cursor/06-sample-data.md`

## Non-goals

Apply suggestion → mutate `dq_rule` / calendar → re-run. Finding override. AI
narratives. Those stay extensions (solution brief §14).
