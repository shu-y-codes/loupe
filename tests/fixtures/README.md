# Fixtures

Tiny, hand-built, committed CSVs, each carrying exactly one planted defect, so a failing test
names the rule it broke. The real corpus is unsuitable as a unit-test fixture: it is 15.5 MB,
it cannot be committed, and it is far too clean to exercise the rule catalogue
(`specs/sample-corpus.md` §8) — four of the seven `error` rules find nothing at all in it.

CSV rather than Parquet on purpose — readable in a diff, editable without tooling, and a
fixture change reviews like any other code change.

## Naming

`<rule_id_lower>.csv`, with `.` becoming `_` (spec §15). A negative case — a file that must
*not* fire — takes a suffix: `weekend_sunday_evening.csv` is `CON.WEEKEND_RECORD`'s.

Slice 1 owns the six ingest fixtures. Slice 2 adds one per rule ID in scope, except where the
spec already assigns an existing file: `null_fields.csv` is the `CMP.NULL_FIELD` fixture (a
*load* of nullable OHLCV in slice 1; findings only once slice 2 writes them), and
`weekend_sunday_evening.csv` is the negative case for `CON.WEEKEND_RECORD`.

## One defect means one defect

A fixture that trips a second rule makes a failure ambiguous, and three of these needed
correcting for exactly that reason: `val_off_tick_price.csv` first put its off-tick close
below `low`, and the two long fixtures repeated an identical bar often enough to trip
`CON.STALE_REPEAT`. Prices in the long fixtures now wobble on the tick for that reason.

Two collisions are left in deliberately, because they are the rules being right rather than
the fixture being wrong: a zero price is also outside its root's plausible band, and every
tiny fixture is a partial session with an incomplete grid. Tests assert on the rule they are
about.

Three rules need a precondition the CSV cannot carry, so the test sets it: `TIM.BEFORE_LISTING`
and `TIM.AFTER_EXPIRY` need `ref.contract` date bounds (inferred, and null for this corpus),
and `TIM.TIMEZONE_MISALIGNED`'s negative case shifts the loaded timestamps back by the offset
it detected.
