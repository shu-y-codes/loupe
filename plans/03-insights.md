# 03 — Insights

**Goal.** Daily OHLCV bars, rolling 15-minute VWAP, oracle test wired.

**Status.** pending

## Done when

1. ✅ Promoted `_notes/cursor/02-analytics-semantics.md` → `specs/analytics-semantics.md`.
   Sample/oracle claims already in `specs/sample-corpus.md` from slice 1. Note marked
   superseded. Do not code from the note.
2. Trade date = session close date. `trade_date_for` shipped in slice 1 and slice 2 consumed
   the grid, so this item is **verification against the promoted spec**, not new code: the
   roll matches spec §1 (driven by `ref.product.session_open_local` / `spans_midnight`, never
   a hardcoded 17:00) and the expected grid matches §2. Assert on **membership, not counts** —
   §2.2.1 shows a calendar-date grouping produces the same 1,380 with different bars.
3. Daily OHLCV aggregation matches spec §3.1 (not vendor close/volume conventions): `open` and
   `close` positional, `high`/`low` extremal, tie-break on `(ts_utc, source_row)`. Ship the
   `arg_min`/`arg_max` struct form; keep the `row_number()` form as the test reference.
4. **`mart.bar_daily` writer for derived bars.** The table has shipped in `ddl.sql` since
   slice 1 and nothing populates it. Materialise under **both** bases (spec §3.3), carrying
   full provenance on every row: `source = 'derived'`, `source_frequency = 'minute'`,
   `close_convention = 'last_trade'`, `expected_count` / `completeness_pct` from the §2 grid,
   `volume_null_count`, `finding_count` / `max_severity` (which findings intersect a bar is
   §3.3's `dq.dq_rule.scope` branch — one resolver, shared with done-when 9's gate), and
   `open_interest` as last reported for the session, never summed. `session_boundary` records
   the resolved boundary in the form `ref.session_calendar` holds it — not a bare `"CME"`;
   §2.2.1 is why the column exists.
   Edge cases per §3.4: no zero-filled bar for an empty session, `expected_count` null on an
   early close rather than a guessed truncated grid.
5. **Vendor daily rows projected into `mart.bar_daily`** as `source = 'vendor'`,
   `source_frequency = 'daily'`, `close_convention = 'settlement'`, with `expected_count` /
   `completeness_pct` null — one supplied row is not a sample of a one-minute grid
   (`specs/data-model.md` §5). Slice 1 loaded these into `stage.market_record` and nothing has
   moved them to the mart; until they exist, done-when 8's vendor branch has nothing to fire
   on and the 43 rows slice 2 measured cannot come back.
6. Rolling 15-minute VWAP is a trailing `RANGE` window, partitioned by
   `(contract, trade_date)`; undefined → `NULL`; does not span sessions. `mart.vwap_15m`
   ships in `ddl.sql`: `specs/data-model.md` §5 declares the view and delegates its body to
   `specs/analytics-semantics.md` §4.6, and neither the view nor the delegation exists in code
   yet. It carries `is_warmup`, `window_volume` and `window_records`, and is the default
   published line (typical price, `clean`). The insights helper takes `basis` (`raw` | `clean`)
   and `price_basis` (`typical` | `close`) and runs the same window against
   `stage.market_record` or `dq.market_record_clean`. `NULL` means `nullif` on a zero
   denominator — never 0, never forward-filled, never interpolated (§4.7).
7. Oracle test: minute→daily open/high/low vs vendor daily; marked optional if samples
   are absent. Tests a definition chosen independently — never used to derive one. Gates are
   owned by `specs/sample-corpus.md` §6.5: agreement **above 95%** per root on complete
   sessions, and the stronger never-narrower invariant (where high/low disagree the vendor
   value is the wider one) **gated on minimum coverage** — ungated it breaks 31 times on sparse
   sessions. Do not assert on `close` or `volume`; assert the explanations. Keep the
   boundary-recovery comparison as a live test. State which `mart.bar_daily.basis` it runs on.
   If it runs on `clean`, read slice 2's recorded exclusion rate
   ([02-quality.md](02-quality.md) done-when 12) **before** hunting an aggregation bug:
   records that slice 2's `error` rules removed are missing from the derived side of the
   comparison but present in the vendor's, and a systematic exclusion on one root shows up here
   as a disagreement that looks like bad aggregation. Running the oracle on `raw` as well
   isolates which of the two it is.
8. Inherited from [02-quality.md](02-quality.md), which deferred them for want of this
   spec: `CON.DERIVED_BAR_INVALID` (severity follows `mart.bar_daily.source` — critical
   and blocks the series when derived, warning when vendor) and `OUT.RETURN_MAD` /
   `OUT.VOLUME_MAD` (MAD method, `0.6745` and `3.5` in `dq.dq_rule.params`, run after
   hard-invalid records are excluded). Fixture and unit test each, per
   `specs/dq-rules-and-scoring.md` §15. These are quality-layer rules: they land in the
   slice-2 catalogue and runners, not in `insights`. **The two-severity pattern** — seed
   `severity='critical'` on `CON.DERIVED_BAR_INVALID` with `params={'vendor_severity': 'warning'}`
   and the runner reads `ctx.param('vendor_severity')` to override, never a hardcoded
   branch. Precedent: `VAL.ZERO_VOLUME_WITH_RANGE` varies by `daily_severity` in the same
   way ([catalogue.py:261-263](src/loupe/quality/catalogue.py#L261-L263),
   [validity.py:192](src/loupe/quality/rules/validity.py#L192)). This keeps the rule's
   declared behaviour seeded with the catalogue and lets a changed param update both
   severities together without a code change.
9. `critical` findings block published analytics for the affected slice — the mechanism
   slice 2 wrote `TIM.TIMEZONE_MISALIGNED` findings against. **The gate lives in `insights`**,
   which `specs/loupe-solution-design.md` §6 settles by elimination: `quality` owns findings
   but must not know about publication, `api` may not hold business math, and `insights` owns
   what is published. Implemented here as one helper resolving whether an open `critical`
   finding intersects a `(contract_id, frequency, trade_date, basis)`, so bars and VWAP
   consult it rather than each embedding the rule — the same resolver done-when 4 uses for
   `finding_count`. `frequency` is in that key for the reason it is in
   `mart.dq_metric_daily`'s: `dq.dq_finding` carries it, and a critical finding on the daily
   config must not block bars derived from the minute tape. The helper returns a
   distinguishable **blocked** result carrying the blocking finding — never an empty series,
   which reads as "no data" — and slice 4 renders that distinction.

## Files to create

- `src/loupe/insights/` — bars, VWAP, compare helpers, the publish gate (no SQL loaders, no
  DQ rule defs)
- `mart.vwap_15m` in `src/loupe/data/ddl.sql`
- Oracle test under `tests/` (skips without `data/samples/`)

## Files to edit

The three inherited rules are quality-layer work and touch slice-2 files:

- `src/loupe/quality/catalogue.py` — three catalogue entries with their params
- `src/loupe/quality/rules/consistency.py` — the `CON.DERIVED_BAR_INVALID` runner
- `src/loupe/quality/rules/` — a new outliers module for the `OUT.*` pair
- `tests/quality/test_catalogue.py` — `DEFERRED_TO_SLICE_3` empties out; the parity test
  fails against the catalogue until it does

## Tests

OHLC invariants; Sunday-evening trade date; **session endpoint membership** (first and last
`ts_exchange` equal the profile's endpoints — the only check that catches a shifted boundary,
§2.2.1); VWAP null on zero volume; session partition; oracle agreement on open/high/low with
the claim owned by `specs/sample-corpus.md`; the three deferred rule IDs from slice 2 plus the
vendor-branch case, where `CON.DERIVED_BAR_INVALID` is a warning that explains rather than
blocks; a `critical` finding blocks its slice and the caller can tell blocked from empty.

## Attach

- `specs/loupe-solution-design.md` §8
- `specs/analytics-semantics.md`, `specs/sample-corpus.md`
- `specs/data-model.md` §5 (`mart.bar_daily` columns, `mart.vwap_15m`)

## Non-goals

Quality rules other than the three deferred above, HTTP, Streamlit, `REC.*`, demo injection.
Do not tune aggregation to match vendor close or volume.
