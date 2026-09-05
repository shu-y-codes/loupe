# 02 — Quality

**Goal.** Core rule families plus DQ score. Fixtures first.

**Status.** pending

## Depends on

`specs/dq-rules-and-scoring.md` defers to `specs/analytics-semantics.md` for the session
grid, bar provenance (`mart.bar_daily.source`) and the MAD method. That spec is **not yet
promoted** — it is done-when 1 of [03-insights.md](03-insights.md). Slice 1 already supplies
the grid this slice needs (`ref.session_calendar.expected_slots_1m`, halt windows,
holidays), so the grid dependency is discharged. Provenance and MAD are not.

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
2. Builtin rules seeded as rows in `dq.dq_rule` (`origin = 'builtin'`) from one declared
   catalogue, in the manner slice 1 seeded `ref.*`. Runners and scoring read thresholds,
   severities and weights from those rows at run time — never a hard-coded branch — so a
   changed param needs no code change. Every rule ID in scope below has a fixture and a
   unit test, named per spec §15. A **parity test** asserts the three sets agree: catalogue
   IDs == registered runners == spec §15.1 in-scope IDs. Without it, a catalogue entry with
   no runner seeds a rule that silently never fires, and a runner with no entry is dead code.
3. **Seeder policy.** In v1 the catalogue is the only author of rules: findings and
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
4. Rule IDs in scope: spec §15.1 core, less the two deferred above — `CMP.*`, `UNQ.*`
   (`UNQ.DUPLICATE_FILE` covered by ingest), `VAL.*`, `CON.*`, `TIM.*`, and both `ROL.*`.
   `ROL.*` are in scope because they suppress completeness noise in the roll window.
5. Completeness bounds come from the derived **liquidity** window (volume floor per
   contract), falling back to `[first_trade_date, last_trade_date]`; the finding records
   which window was used.
6. Session-grained `CMP.*` **refuse to evaluate** when calendar, halt or holiday inputs are
   unavailable, rather than evaluating without them. Tested as its own behaviour.
7. A rule pass opens a `dq.dq_run` (with `ruleset_hash`) and closes it with a status and
   finding count. Findings land in `dq.dq_finding`; ranges are one row, not one per slot.
8. Dimension weights live in `dq.score_weight`, seeded from spec §11.2 and read at scoring
   time. `dq.dq_rule.triage_weight` orders the fix-first worklist and is never a score input
   (§11.4); each rule with open findings also reports `score_if_resolved`, the §11.1 recompute
   with its defect count zeroed. A test asserts triage weight cannot move any score.
9. Score: per-dimension 0–100; overall = weighted mean over dimensions in scope;
   renormalise; expose scope fields (`dimensions_in_scope`, `dimensions_not_in_scope`,
   `weight_denominator`, `scope_signature`, per-dimension denominator and basis).
   Per-dimension rows persisted to `mart.dq_metric_daily`. Below `params.min_records`,
   "insufficient data" rather than a score.
10. Raw records stay immutable; cleaning decisions are rows in `dq.cleaning_action`; the
    clean view is derived; changelog is replayable. Note that default cleaning (spec §14 —
    `exclude` on `error`, `dedupe_drop` on exact duplicates) is **automatic policy, not a
    user action**, and still applies: "report-only" bounds what a *user* can do to rules and
    findings, not whether the engine cleans.
11. `TIM.TIMEZONE_MISALIGNED` fires `critical` on a shifted derivative fixture. Blocking
    analytics on it is slice 3; this slice writes the finding only.
12. **Exclusion rate measured and recorded in this plan** before slice 3 builds on
    `dq.market_record_clean`. Seven `error` rules land at once (`CMP.NULL_FIELD`,
    `UNQ.KEY_CONFLICT`, `VAL.NON_POSITIVE_PRICE`, `VAL.NEGATIVE_VOLUME`, `CON.HIGH_LT_LOW`,
    `CON.OPEN_OUT_OF_RANGE`, `CON.CLOSE_OUT_OF_RANGE`) plus `dedupe_drop`, and this is the
    first time anything is excluded at all. Report `n` of `N` records excluded, split by
    rule and by root, and say whether any concentration looks systematic rather than
    incidental. A quirk tripping one rule on a few percent of one root would surface in
    slice 3 as an oracle-test failure that looks like an aggregation bug (spec §17).
    Measured facts belong here, as in [01-data-ingest.md](01-data-ingest.md).

## Files to create

- `src/loupe/quality/` — rule catalogue + seed, rule runners, scoring, finding writers
  (no charts)
- `tests/fixtures/*.csv` — committed; one planted defect per fixture
- Tests under `tests/quality/`

`REC.*`, patterns, and suggestions wait for [06-rec-suggestions-demo.md](06-rec-suggestions-demo.md).

## Tests

Each rule ID in scope; property checks (cleaning idempotent; a record counted at most once
per dimension; overall is the renormalised weighted mean over dimensions in scope). Edge
fixtures named in solution brief §13 (dup, gap, `high < low`, Sunday-evening negative case,
etc.).

## Attach

- `specs/loupe-solution-design.md` §9
- `specs/dq-rules-and-scoring.md`
- `specs/data-model.md` §4 (finding, run, cleaning-action, metric shapes)

## Non-goals

Insights maths, API, UI, apply/override, AI narratives, `REC.*` (slice 6),
`CON.DERIVED_BAR_INVALID` and `OUT.*` (slice 3, see above).
