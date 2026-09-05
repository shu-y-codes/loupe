# 03 — Insights

**Goal.** Daily OHLCV bars, rolling 15-minute VWAP, oracle test wired.

**Status.** pending

## Done when

1. ✅ Promoted `_notes/cursor/02-analytics-semantics.md` → `specs/analytics-semantics.md`.
   Sample/oracle claims already in `specs/sample-corpus.md` from slice 1. Note marked
   superseded. Do not code from the note.
2. Trade date = session close date; expected grid matches the promoted spec.
3. Daily OHLCV aggregation matches the spec (not vendor close/volume conventions).
4. Rolling 15-minute VWAP is a trailing `RANGE` window, partitioned by
   `(contract, trade_date)`; undefined → `NULL`; does not span sessions.
5. Oracle test: minute→daily open/high/low vs vendor daily; marked optional if samples
   are absent. Tests a definition chosen independently — never used to derive one. State
   which `mart.bar_daily.basis` it runs on. If it runs on `clean`, read slice 2's recorded
   exclusion rate ([02-quality.md](02-quality.md) done-when 12) **before** hunting an
   aggregation bug: records that slice 2's `error` rules removed are missing from the
   derived side of the comparison but present in the vendor's, and a systematic exclusion
   on one root shows up here as a disagreement that looks like bad aggregation. Running the
   oracle on `raw` as well isolates which of the two it is.
6. Inherited from [02-quality.md](02-quality.md), which deferred them for want of this
   spec: `CON.DERIVED_BAR_INVALID` (severity follows `mart.bar_daily.source` — critical
   and blocks the series when derived, warning when vendor) and `OUT.RETURN_MAD` /
   `OUT.VOLUME_MAD` (MAD method). Fixture and unit test each, per spec §15.
7. `critical` findings block published analytics for the affected slice — the mechanism
   slice 2 wrote `TIM.TIMEZONE_MISALIGNED` findings against.

## Files to create

- `src/loupe/insights/` — bars, VWAP, compare helpers (no SQL loaders, no DQ rule defs)
- Oracle test under `tests/` (skips without `data/samples/`)

## Tests

OHLC invariants; Sunday-evening trade date; VWAP null on zero volume; session partition;
oracle agreement on open/high/low with the claim owned by `specs/sample-corpus.md`; the
two deferred rule IDs from slice 2.

## Attach

- `specs/loupe-solution-design.md` §8
- `specs/analytics-semantics.md`, `specs/sample-corpus.md`

## Non-goals

Quality rules other than the two deferred above, HTTP, Streamlit, `REC.*`, demo injection. Do not tune aggregation to
match vendor close or volume.
