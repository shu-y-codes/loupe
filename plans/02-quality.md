# 02 — Quality

**Goal.** Core rule families plus DQ score. Fixtures first.

**Status.** pending

## Done when

1. Promote `_notes/cursor/04-dq-rules-and-scoring.md` → `specs/dq-rules-and-scoring.md`.
   Do not code from the note.
2. Rules are rows in `dq.dq_rule`; each v1 core ID has a fixture and a unit test.
3. Findings written for completeness, uniqueness, validity, consistency, timeliness
   (core families in the promoted spec). Score: per-dimension 0–100; overall = weighted
   mean over dimensions in scope; renormalise; expose scope fields.
4. Raw records stay immutable; clean view is derived; changelog is replayable.

## Files to create

- `quality/` — rule runners, scoring, finding writers (no charts)
- `tests/fixtures/*.csv` — committed; one rule / helper per fixture
- Tests under `tests/quality/`

`REC.*`, patterns, and suggestions wait for [06-rec-suggestions-demo.md](06-rec-suggestions-demo.md).

## Tests

Each core rule ID from the promoted spec; property checks (cleaning idempotent; parts
sum to whole). Edge fixtures named in solution brief §13 (dup, gap, `high < low`, etc.).

## Attach

- `specs/loupe-solution-design.md` §9
- After promote: `specs/dq-rules-and-scoring.md`
- Research until promoted: `_notes/cursor/04-dq-rules-and-scoring.md`

## Non-goals

Insights maths, API, UI, apply/override, AI narratives, `REC.*` (slice 6).
