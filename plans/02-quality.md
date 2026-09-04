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
2. Builtin rules seeded as rows in `dq.dq_rule` (`origin = 'builtin'`), params and default
   weights in config, not code branches. Every rule ID in scope below has a fixture and a
   unit test, named per spec §15.
3. Rule IDs in scope: spec §15.1 core, less the two deferred above — `CMP.*`, `UNQ.*`
   (`UNQ.DUPLICATE_FILE` covered by ingest), `VAL.*`, `CON.*`, `TIM.*`, and both `ROL.*`.
   `ROL.*` are in scope because they suppress completeness noise in the roll window.
4. Completeness bounds come from the derived **liquidity** window (volume floor per
   contract), falling back to `[first_trade_date, last_trade_date]`; the finding records
   which window was used.
5. Session-grained `CMP.*` **refuse to evaluate** when calendar, halt or holiday inputs are
   unavailable, rather than evaluating without them. Tested as its own behaviour.
6. A rule pass opens a `dq.dq_run` (with `ruleset_hash`) and closes it with a status and
   finding count. Findings land in `dq.dq_finding`; ranges are one row, not one per slot.
7. Score: per-dimension 0–100; overall = weighted mean over dimensions in scope;
   renormalise; expose scope fields (`dimensions_in_scope`, `dimensions_not_in_scope`,
   `weight_denominator`, `scope_signature`, per-dimension denominator and basis).
   Per-dimension rows persisted to `mart.dq_metric_daily`. Below `params.min_records`,
   "insufficient data" rather than a score.
8. Raw records stay immutable; cleaning decisions are rows in `dq.cleaning_action`; the
   clean view is derived; changelog is replayable.
9. `TIM.TIMEZONE_MISALIGNED` fires `critical` on a shifted derivative fixture. Blocking
   analytics on it is slice 3; this slice writes the finding only.

## Files to create

- `src/loupe/quality/` — rule runners, scoring, finding writers, builtin rule seed (no charts)
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
