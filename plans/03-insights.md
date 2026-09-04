# 03 — Insights

**Goal.** Daily OHLCV bars, rolling 15-minute VWAP, oracle test wired.

**Status.** pending

## Done when

1. Promote `_notes/cursor/02-analytics-semantics.md` → `specs/analytics-semantics.md`
   **before** writing insights code. Promote committed sample/oracle claims from
   `_notes/cursor/06-sample-data.md` into `specs/sample-corpus.md` if not already done
   in slice 1.
2. Trade date = session close date; expected grid matches the promoted spec.
3. Daily OHLCV aggregation matches the spec (not vendor close/volume conventions).
4. Rolling 15-minute VWAP is a trailing `RANGE` window, partitioned by
   `(contract, trade_date)`; undefined → `NULL`; does not span sessions.
5. Oracle test: minute→daily open/high/low vs vendor daily; marked optional if samples
   are absent. Tests a definition chosen independently — never used to derive one.

## Files to create

- `insights/` — bars, VWAP, compare helpers (no SQL loaders, no DQ rule defs)
- Oracle test under `tests/` (skips without `data/samples/`)

## Tests

OHLC invariants; Sunday-evening trade date; VWAP null on zero volume; session partition;
oracle agreement on open/high/low with the claim owned by `specs/sample-corpus.md`.

## Attach

- `specs/loupe-solution-design.md` §8
- After promote: `specs/analytics-semantics.md`, `specs/sample-corpus.md`
- Research until promoted: `_notes/cursor/02-analytics-semantics.md`,
  `_notes/cursor/06-sample-data.md`

## Non-goals

Quality rules, HTTP, Streamlit, `REC.*`, demo injection. Do not tune aggregation to
match vendor close or volume.
