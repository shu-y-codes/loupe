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

## `REC.*` comes in pairs

A cross-frequency defect cannot live in one file. Each reconciliation rule therefore has
`<rule_id_lower>_minute.csv` and `<rule_id_lower>_daily.csv`, loaded together, and the defect
is the *disagreement between them* rather than anything wrong with either on its own — which
is the whole point of the family (spec §8).

Each pair carries a session that fires and a session that does not, because a filter needs an
input it admits and an input it rejects to be tested at all (`specs/loupe-solution-design.md`
§13). `rec_volume_shortfall_*` is the clearest: one session where the tape is short and one
where it legitimately exceeds the vendor, which must stay silent (§8.3).

Session volumes are above the 1,000 liquidity floor on purpose. Below it the coverage window
falls back to the listed span, the reconcilable window stops being the intersection of the two
observed spans, and `rec_session_only_in_one_*`'s out-of-window session would fire.

Four fixtures here are not rule fixtures at all and are named for what they feed rather than
for a rule ID. `insights_pattern_hourly.csv` spreads 96 records evenly over four hours and puts
every off-tick close in one of them, so the lift is exactly 4.0 and a reader can check the
arithmetic by hand. `insights_pattern_settlement_*.csv` is the corpus's own shape — 24 sessions
whose vendor close sits at the settlement mark rather than at the last trade — and drives the
suggestion generator. `injection_base.csv` is deliberately *clean*: it is what
`loupe.demo.injection` derives a labelled defective copy from, and a base that already tripped
those rules would let every injection test pass against an injector that did nothing.

The coverage gate is the one precondition these CSVs cannot carry: `min_coverage_pct` is 0.98
of 1,380 calendar slots and no committed fixture is going to hold 1,353 rows. The tests lower
it in the seeded row, the way a deployment would, and assert both sides of the gate separately.

Three rules need a precondition the CSV cannot carry, so the test sets it: `TIM.BEFORE_LISTING`
and `TIM.AFTER_EXPIRY` need `ref.contract` date bounds (inferred, and null for this corpus),
and `TIM.TIMEZONE_MISALIGNED`'s negative case shifts the loaded timestamps back by the offset
it detected.
