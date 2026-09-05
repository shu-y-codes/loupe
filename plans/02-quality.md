# 02 — Quality

**Goal.** Core rule families plus DQ score. Fixtures first.

**Status.** done — 2026-09-05

## Depends on

`specs/dq-rules-and-scoring.md` defers to `specs/analytics-semantics.md` for the session
grid, bar provenance (`mart.bar_daily.source`) and the MAD method. That spec is now
promoted (done-when 1 of [03-insights.md](03-insights.md)). Slice 1 already supplied
the grid this slice needed (`ref.session_calendar.expected_slots_1m`, halt windows,
holidays). Provenance and MAD wait on slice 3's bar writer and `OUT.*` runners.

**Deferral decision.** `CON.DERIVED_BAR_INVALID` and `OUT.RETURN_MAD` / `OUT.VOLUME_MAD`
move to slice 3, after the promotion. `CON.DERIVED_BAR_INVALID` severity is a function of
bar provenance and there is no writer for `mart.bar_daily` until slice 3; `OUT.*` has no
defined method until then. Both are `info` or vendor-branch `warning` in the common case
and neither auto-excludes, so nothing downstream in this slice waits on them. Vendor daily
rows still get record-scope OHLC checks here via `CON.HIGH_LT_LOW` and friends. This
narrows the slice-2 column of the spec's build-sequence table, which is sequence and so
belongs to plans.

## Done when

1. ✅ Promoted `_notes/cursor/04-dq-rules-and-scoring.md` → `specs/dq-rules-and-scoring.md`.
   Note marked superseded. Do not code from the note.
2. ✅ Builtin rules seeded as rows in `dq.dq_rule` (`origin = 'builtin'`) from one declared
   catalogue, in the manner slice 1 seeded `ref.*`. Runners and scoring read thresholds,
   severities and weights from those rows at run time — never a hard-coded branch — so a
   changed param needs no code change. Every rule ID in scope below has a fixture and a
   unit test, named per spec §15. A **parity test** asserts the three sets agree: catalogue
   IDs == registered runners == spec §15.1 in-scope IDs. Without it, a catalogue entry with
   no runner seeds a rule that silently never fires, and a runner with no entry is dead code.
3. ✅ **Seeder policy.** In v1 the catalogue is the only author of rules: findings and
   suggestions are report-only (spec §13, locked decision 10), so there is no path by which
   a user or an applied suggestion writes `dq.dq_rule`. The seeder therefore inserts absent
   rule IDs and refreshes every `origin = 'builtin'` row to catalogue values, so a corrected
   default reaches an existing database on re-seed. Idempotent; re-running changes nothing
   when the catalogue has not changed.

   Write the extensibility seam now, even though nothing exercises it: the refresh is
   guarded `WHERE origin = 'builtin'`, and rows that are absent because someone deleted
   them are re-inserted, so **disabling is `enabled = FALSE`, never a delete**. A test
   plants an `origin = 'user'` row and asserts a re-seed leaves it untouched — otherwise the
   guard is untested code that will have rotted by the time slice 6+ needs it. When apply /
   override arrive, the seeder does not change; only the report of what it skipped does.
4. ✅ Rule IDs in scope: spec §15.1 core, less the two deferred above — `CMP.*`, `UNQ.*`
   (`UNQ.DUPLICATE_FILE` covered by ingest), `VAL.*`, `CON.*`, `TIM.*`, and both `ROL.*`.
   `ROL.*` are in scope because they suppress completeness noise in the roll window.
5. ✅ Completeness bounds come from the derived **liquidity** window (volume floor per
   contract), falling back to `[first_trade_date, last_trade_date]`; the finding records
   which window was used.
6. ✅ Session-grained `CMP.*` **refuse to evaluate** when calendar, halt or holiday inputs are
   unavailable, rather than evaluating without them. Tested as its own behaviour.
7. ✅ A rule pass opens a `dq.dq_run` (with `ruleset_hash`) and closes it with a status and
   finding count. Findings land in `dq.dq_finding`; ranges are one row, not one per slot.
8. ✅ Dimension weights live in `dq.score_weight`, seeded from spec §11.2 and read at scoring
   time. `dq.dq_rule.triage_weight` orders the fix-first worklist and is never a score input
   (§11.4); each rule with open findings also reports `score_if_resolved`, the §11.1 recompute
   with its defect count zeroed. A test asserts triage weight cannot move any score.
9. ✅ Score: per-dimension 0–100; overall = weighted mean over dimensions in scope;
   renormalise; expose scope fields (`dimensions_in_scope`, `dimensions_not_in_scope`,
   `weight_denominator`, `scope_signature`, per-dimension denominator and basis).
   Per-dimension rows persisted to `mart.dq_metric_daily`. Below `params.min_records`,
   "insufficient data" rather than a score.
10. ✅ Raw records stay immutable; cleaning decisions are rows in `dq.cleaning_action`; the
    clean view is derived; changelog is replayable. Note that default cleaning (spec §14 —
    `exclude` on `error`, `dedupe_drop` on exact duplicates) is **automatic policy, not a
    user action**, and still applies: "report-only" bounds what a *user* can do to rules and
    findings, not whether the engine cleans.
11. ✅ `TIM.TIMEZONE_MISALIGNED` fires `critical` on a shifted derivative fixture. Blocking
    analytics on it is slice 3; this slice writes the finding only.
12. ✅ **Exclusion rate measured and recorded in this plan** before slice 3 builds on
    `dq.market_record_clean`. Seven `error` rules land at once (`CMP.NULL_FIELD`,
    `UNQ.KEY_CONFLICT`, `VAL.NON_POSITIVE_PRICE`, `VAL.NEGATIVE_VOLUME`, `CON.HIGH_LT_LOW`,
    `CON.OPEN_OUT_OF_RANGE`, `CON.CLOSE_OUT_OF_RANGE`) plus `dedupe_drop`, and this is the
    first time anything is excluded at all. Report `n` of `N` records excluded, split by
    rule and by root, and say whether any concentration looks systematic rather than
    incidental. A quirk tripping one rule on a few percent of one root would surface in
    slice 3 as an oracle-test failure that looks like an aggregation bug (spec §17).
    Measured facts belong here, as in [01-data-ingest.md](01-data-ingest.md).

## Files created

- `src/loupe/quality/` — `catalogue` (31 declared rules + §11.2 weights), `seed`,
  `registry`, `windows`, `rules/` (one module per dimension, 30 runners), `runner`,
  `cleaning`, `scoring`, `errors`. No charts, no HTTP.
- `tests/fixtures/` — 29 new rule CSVs, one planted defect each; `null_fields.csv` and
  `weekend_sunday_evening.csv` are reused from slice 1, as spec §15 assigns them.
- `tests/quality/` — 119 tests across catalogue/parity, the five rule families, cleaning,
  scoring, and the corpus exclusion measurement (the last five are skipped without the corpus).

`REC.*`, patterns, and suggestions wait for [06-rec-suggestions-demo.md](06-rec-suggestions-demo.md).

## Measured: what the first exclusion actually removes

Done-when 12, run over the fetched corpus (48 files, 711,484 records — 681,382 minute,
30,102 daily). Guarded by `tests/quality/test_exclusion_rate.py`.

> **Superseded 2026-09-05, and kept because it is a measurement.** The numbers below are what
> the system did when this slice shipped, and the last paragraph is the reason they changed:
> slice 3's `CON.DERIVED_BAR_INVALID` arrived, and `CON.CLOSE_OUT_OF_RANGE` now drops to
> `warning` on a daily bar interval (`specs/dq-rules-and-scoring.md` §6). **41 of the 43 rows
> came back.** The current measurement is 2 records of 711,484 — 0.000281% — both
> `CON.OPEN_OUT_OF_RANGE`, one ES daily and one SR3 daily; the 42 `CON.CLOSE_OUT_OF_RANGE`
> findings are still written, now at `warning`, and the ESZ25 row that trips both rules is
> one of the two still excluded. Read what follows as the snapshot it was, not as the
> system's behaviour today.

**43 records of 711,484 excluded: 0.0060%.** 44 cleaning decisions, because one `ESZ25`
daily row trips both range rules. Four of the seven `error` rules the plan names fire **zero**
times across the whole corpus — no nulls, no key conflicts, no non-positive prices, no
negative volumes — and `dedupe_drop` never fires either. Only two rules exclude anything:

| Rule | Records |
|---|---|
| `CON.CLOSE_OUT_OF_RANGE` | 42 |
| `CON.OPEN_OUT_OF_RANGE` | 2 |

| Root, config | Excluded | Records | Rate |
|---|---|---|---|
| CL daily | 28 | 10,310 | 0.272% |
| ES daily | 7 | 3,505 | 0.200% |
| SR3 daily | 5 | 3,882 | 0.129% |
| ZC daily | 3 | 3,761 | 0.080% |
| **every minute config** | **0** | **681,382** | **0.000%** |

**The concentration is systematic, not incidental, and it has a market explanation.** Every
excluded record is a vendor **daily** row; 39 of the 44 decisions land on a zero-volume row,
39 on a row with `open = high = low`, and 36 on both. That is an untraded deferred contract
carrying its prior range with a settlement struck elsewhere — the phenomenon `specs/sample-corpus.md` §7.5 counts
as "the 43 invalid-OHLC daily rows", reproduced here independently. The remaining handful are
the same thing at one-lot volume, mostly SR3 settling half a tick outside its own range.

**Consequence for [03-insights.md](03-insights.md), and it is the reason to measure first.**
Spec §6 says this severity should follow bar provenance: on the vendor branch,
`CON.DERIVED_BAR_INVALID` flags and explains rather than blocking, because a settlement is not
obliged to sit inside the traded range. That rule is deferred to slice 3, so until it lands
these 43 rows leave `dq.market_record_clean` on the record-scope check instead. Slice 3 should
expect the vendor daily bars to come back when provenance arrives, and should not read a
43-row difference between the raw and clean daily bases as an aggregation bug.

**What actually happened** (2026-09-05, and the reason for the banner above). Provenance
arrived and 41 of the 43 rows came back — not by weakening `CON.DERIVED_BAR_INVALID`, but by
giving `CON.CLOSE_OUT_OF_RANGE` the same interval-sensitive severity
`VAL.ZERO_VOLUME_WITH_RANGE` already had. A daily close is a settlement; only an intraday
close is a trade obliged to sit inside its own range. The rows now reach `mart.bar_daily` and
the vendor branch of `CON.DERIVED_BAR_INVALID` explains them there, so a user sees *why* a
contract-day is unusual instead of not seeing the contract-day. The two rows still excluded
are `CON.OPEN_OUT_OF_RANGE`, which has no settlement story: an open is a trade at either
granularity.

## Tests

Each rule ID in scope; property checks (cleaning idempotent; a record counted at most once
per dimension; overall is the renormalised weighted mean over dimensions in scope). Edge
fixtures named in solution brief §13 (dup, gap, `high < low`, Sunday-evening negative case,
etc.).

**Spec corrections this slice made**, both surfaced by writing the rule rather than assumed.

`VAL.NON_INTEGER_VOLUME` could not fire as slice 1 left things. `stage.market_record.volume`
is a `BIGINT` because volume is a count of contracts, and DuckDB casts `'10.5'` to `11`
rather than refusing it — so a fractional volume loaded and its fraction was gone before any
rule could see it. It is not `STR.NON_NUMERIC_VOLUME` either: that code is for a value that
is not a number, and rejecting the row would have lost its OHLC as well. `specs/data-model.md`
§3 and §3.1 now carry `volume_source`, the verbatim label kept **only** when it does not
parse as an integer — null on every one of the 711,484 corpus rows, and non-null exactly
where there is something to report.

Two readings of §11.1 had to be reconciled: it writes completeness as
`actual_records / expected_records`, and it also says every dimension counts its defective
records at most once. `CMP.NULL_FIELD` is the completeness dimension's record-scope rule, so
under the first reading alone it could never move a score and its `score_if_resolved` would
always be zero. Resolved by reading `actual_records` as records that are present **and
complete**: missing slots lower completeness by being absent from the numerator, and
incomplete records lower it by being subtracted from it. `mart.dq_metric_daily` already
carries `actual_records` and `affected_records` side by side, which is what keeps the two
effects separable rather than merged into one number.

## Attach

- `specs/loupe-solution-design.md` §9
- `specs/dq-rules-and-scoring.md`
- `specs/data-model.md` §4 (finding, run, cleaning-action, metric shapes)

## Non-goals

Insights maths, API, UI, apply/override, AI narratives, `REC.*` (slice 6),
`CON.DERIVED_BAR_INVALID` and `OUT.*` (slice 3, see above).
