# Loupe — DQ rules and scoring

**Normative.** Rule catalogue, severities, score formula, pattern and suggestion shapes, and
the fixture-to-rule mapping. Promoted from research `_notes/cursor/04-dq-rules-and-scoring.md`
(now archaeology). Summary and v1 boundary: `specs/loupe-solution-design.md` §9. Storage:
`specs/data-model.md` §4. Sample rates used as calibration: `specs/sample-corpus.md` §7.
Session grid, bar provenance and MAD method: `specs/analytics-semantics.md`.

Revised 2026-09-05: promoted from research; first normative version.

**Scope of authority.** This spec owns *rule IDs, triggers, params, cleaning consequences, the
score, and the fixture map*. It does not own DDL, sample measurements, or HTTP envelopes
(`specs/api-contract.md` when promoted). Every v1 core rule ID seeds a row in `dq.dq_rule`
except `STR.*`, which are parse rejects in `stage.record_reject`.

**Build sequence** (plans, not a second spec):

| Content | v1? | When |
|---|---|---|
| `STR.*` | yes | Slice 1 (ingest; already shipped) |
| `CMP.*` `UNQ.*` `VAL.*` `CON.*` `TIM.*` `ROL.*`, score | yes | Slice 2 |
| `OUT.*` | yes, optional | Slice 2 |
| `REC.*`, patterns, report-only suggestions | yes | Slice 6 |
| Suggestion apply / dismiss, finding override, AI narratives | **extension** | not v1 |

---

## 1. Dimensions, severities, cleaning

Six dimensions. The first five are always in scope. Reconciliation is **conditional**: it exists
only when the user has supplied both `daily` and `minute` covering the same contract.

| Dimension | Question |
|---|---|
| Completeness | Is anything missing? |
| Uniqueness | Is anything counted twice? |
| Validity | Is each value individually possible? |
| Consistency | Do values agree with each other and with the calendar? |
| Timeliness | Are timestamps where they should be? |
| Reconciliation | Do two independent representations of the same session agree? |

| Severity | Meaning | Default cleaning |
|---|---|---|
| `info` | Informational; never affects cleaning or the score | none |
| `warning` | Suspicious; flag only | none |
| `error` | Defect | `exclude` the affected records |
| `critical` | Structural; blocks the series (no analytics published for that slice) | exclude + block |

Exceptions are named on the rule (`VAL.OFF_TICK_PRICE` stays warning / flag-only even when
systematic; `CON.DERIVED_BAR_INVALID` severity follows bar provenance). Policy lives in
`dq.dq_rule` and `dq.cleaning_action`, not in code branches. Raw records stay immutable
(locked decision 1).

`dq.dq_rule.dimension` is one of the six names above. `ROL.*` rows use `completeness` (they
exist to suppress completeness noise). `OUT.*` rows use `validity` and are `info`, so they
never enter the validity defect count.

---

## 2. Structural rejects — `STR.*`

Parse failures. Rows in `stage.record_reject`, **not** `dq.dq_finding`, because the record
could not be loaded. Ingest already implements these (slice 1).

| Code | Scope | Trigger |
|---|---|---|
| `STR.MISSING_REQUIRED_COLUMN` | file | A required field is absent from the header. Rejects the whole file (`MissingRequiredColumn`). |
| `STR.UNPARSEABLE_ROW` | record | Row cannot be split into the expected field count. |
| `STR.BAD_TIMESTAMP` | record | Timestamp does not parse under any accepted format. |
| `STR.NON_NUMERIC_PRICE` | record | A price field contains a non-numeric string. |
| `STR.NON_NUMERIC_VOLUME` | record | Volume contains a non-numeric string. |
| `STR.UNKNOWN_CONTRACT_FORMAT` | record | Contract identifier cannot be parsed. Warn and continue; do not reject. |

`STR.NON_NUMERIC_PRICE` (the string `"N/A"` — unparseable, reject) is not `CMP.NULL_FIELD`
(an empty cell — parseable as null, load it and flag it). Conflating them makes the null
case unreportable.

---

## 3. Completeness — `CMP.*`

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `CMP.NULL_FIELD` | error | record | Any of open/high/low/close/volume is null. `details.field` names it. |
| `CMP.MISSING_TIMESTAMP` | warning | session | Contiguous run of expected grid slots with no record. One finding per run; `affected_rows` = slot count. |
| `CMP.SESSION_MISSING` | error | session | No records at all for an active contract on a non-holiday session. |
| `CMP.PARTIAL_SESSION` | warning | session | `completeness_pct` below `params.threshold` (default 0.95). |
| `CMP.SPARSE_SERIES` | info | series | Contract has fewer than `params.min_sessions` sessions overall. |

**Suppressions are a precondition of this family, not a refinement.** All five rules are
suppressed outside the contract's tradable window, on holidays, and inside halt windows
(grid owned by `specs/analytics-semantics.md`). If those inputs are unavailable,
`CMP.SESSION_MISSING` (and the other session-grained rules) **must refuse to evaluate**,
rather than evaluate without them.

The window is a **liquidity** window: first and last session whose volume exceeds
`params.volume_floor`, derived per contract from the data. Fall back to
`[first_trade_date, last_trade_date]` only when volume is unavailable, and record on the
finding which window was used. The listed span is the wrong bound — a contract is listed
years before it trades. Calibration and the `ESZ25` deferred-session count:
`specs/sample-corpus.md` §7.4.

---

## 4. Uniqueness — `UNQ.*`

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `UNQ.EXACT_DUPLICATE` | warning | record | Two or more rows identical across all fields. |
| `UNQ.KEY_CONFLICT` | error | record | Same `(contract_id, frequency, ts_utc)`, differing OHLCV. |
| `UNQ.DUPLICATE_FILE` | warning | file | `file_hash` already ingested. |

Exact duplicate: keep the lowest `source_row` (`dedupe_drop`). Key conflict: exclude **all**
rows in the conflict — there is no principled winner inside the file. Evaluated **within a
frequency, never across** (`specs/data-model.md` §4.1).

`UNQ.DUPLICATE_FILE` is the quality-layer name for the event ingest already refuses
(`DuplicateFileError` / unique `file_hash`). No finding row is required when the batch never
lands.

```sql
-- exact duplicates
SELECT contract_id, frequency, ts_utc, open, high, low, close, volume, count(*) AS n
FROM stage.market_record
GROUP BY ALL HAVING count(*) > 1;

-- key conflicts: same key, more than one distinct value tuple
SELECT contract_id, frequency, ts_utc,
       count(*) AS rows,
       count(DISTINCT (open, high, low, close, volume)) AS variants
FROM stage.market_record
GROUP BY contract_id, frequency, ts_utc
HAVING count(DISTINCT (open, high, low, close, volume)) > 1;
```

---

## 5. Validity — `VAL.*`

Each value judged on its own.

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `VAL.NON_POSITIVE_PRICE` | error | record | Any price `<= 0`. |
| `VAL.NEGATIVE_VOLUME` | error | record | `volume < 0`. |
| `VAL.NON_INTEGER_VOLUME` | warning | record | Volume has a fractional part. |
| `VAL.OFF_TICK_PRICE` | warning | record | Price is not a multiple of the tick for `(root, frequency, field)`. |
| `VAL.ZERO_VOLUME_WITH_RANGE` | warning | record | `volume = 0` but `high > low`, at **intraday** frequency. |
| `VAL.PRICE_MAGNITUDE` | warning | record | Price outside `params.plausible_range` for the root. Catches decimal-shift errors. |
| `VAL.EXTREME_VOLUME` | info | record | Volume above `params.max_plausible`. |

**The tick lattice is a property of `(root, frequency, field)`, not of the root alone.** A
traded price must sit on the tick; a settlement price is under no such obligation. Seed the
lattice from the data (largest increment on which every observed price of that triple lies)
and treat seeded values as overridable calibration, not as a specification. Mark
settlement-bearing fields `exempt` on `ref.tick` rather than inventing a fake lattice.
`VAL.OFF_TICK_PRICE` is flag-only, never exclude: a systematic off-tick pattern across a
whole contract more likely means the tick reference is wrong. Worked example (VX daily
`close`): `specs/sample-corpus.md` §7.3.

Intraday vs daily for `VAL.ZERO_VOLUME_WITH_RANGE`: a minute bar is emitted because something
transacted; a daily summary is published for listed contracts whether or not they traded.
Ask **intraday** of `bar_interval`, not of `frequency = 'minute'`. Default params
`{"frequencies": ["intraday"], "daily_severity": "info"}` — at daily, disable or drop to
`info` (settlement-only row). A different vendor may suppress untraded daily rows entirely.

`VAL.PRICE_MAGNITUDE` bands are per root (sample-corpus §7.2).

---

## 6. Consistency — `CON.*`

Relationships between fields, and between records and the calendar.

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `CON.HIGH_LT_LOW` | error | record | `high < low`. |
| `CON.OPEN_OUT_OF_RANGE` | error | record | `open` outside `[low, high]`. |
| `CON.CLOSE_OUT_OF_RANGE` | error | record | `close` outside `[low, high]`. |
| `CON.WEEKEND_RECORD` | error | record | Derived **session** date falls on Saturday or Sunday. Never evaluated on a vendor-supplied date column. |
| `CON.RECORD_IN_HALT` | warning | record | Timestamp inside a maintenance break or trading halt. |
| `CON.RECORD_ON_HOLIDAY` | warning | record | Record on a calendar holiday session. |
| `CON.STALE_REPEAT` | warning | session | `params.n` consecutive records (default 30, per-root override) with identical OHLC and non-zero volume. |
| `CON.PRICE_JUMP` | info | record | Absolute log return between consecutive records exceeds `params.threshold`. |
| `CON.DERIVED_BAR_INVALID` | see below | session | A daily bar violates the OHLC invariants. |

**`CON.WEEKEND_RECORD` is computed on the derived session date and on nothing else.** A
vendor `trading_date` is an assertion, not a fact; feeding it to this rule inherits the
vendor's calendar-date meaning (Sunday-evening CME trading labelled Sunday). Derive the
session date from the timestamp and the configured boundary, record the boundary on the
batch, and treat any vendor date column as something to reconcile against. Measured
contrast: `specs/sample-corpus.md` §7.1.

**`CON.STALE_REPEAT` default `n` is not global.** A flat price for many consecutive minutes
is ordinary on an illiquid rate contract and a feed failure on ES. Global default `n = 30`;
allow `params.n_by_root`. Prefer scaling to observed liquidity (flat-bar rate or median
inter-trade interval for `(root, frequency)`). Seeded per-root values are calibration for
this corpus. Rates that forced `n = 30`: sample-corpus §7.1.

**`CON.DERIVED_BAR_INVALID` severity follows bar provenance** (`mart.bar_daily.source`;
semantics in `specs/analytics-semantics.md`):

| Bar provenance | Severity | Meaning |
|---|---|---|
| Derived by Loupe from validated records | critical | A defect escaped record validation; blocks the series. |
| Supplied by a vendor daily file | warning | The vendor's close is a settlement and may sit outside the traded range. Flag, explain, never block. |

On the vendor branch the finding names the phenomenon (settlement outside a stale or
carried range) and links to `REC.CLOSE_CONVENTION` for the same session where one exists.
Calibration: sample-corpus §7.5 (43 vendor daily rows).

---

## 7. Timeliness — `TIM.*`

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `TIM.OUT_OF_ORDER` | warning | record | `ts_utc` decreases as `source_row` increases. |
| `TIM.FUTURE_TIMESTAMP` | error | record | Timestamp after ingest time. |
| `TIM.BEFORE_LISTING` | warning | record | Before `ref.contract.first_trade_date`. |
| `TIM.AFTER_EXPIRY` | error | record | After `ref.contract.last_trade_date`. |
| `TIM.OFF_GRID` | warning | record | Timestamp not aligned to the inferred interval boundary. |
| `TIM.TIMEZONE_MISALIGNED` | critical | file | Session activity histogram is offset from the expected session by a whole number of hours. |

`TIM.TIMEZONE_MISALIGNED`: if the file's timezone was misread, every downstream number is
wrong (trade dates, daily bars, gaps, VWAP session boundaries) and no other rule notices.
Detect by comparing the file's 60-minute activity dead zone to the expected maintenance
break. Fire `critical`, block analytics, and offer the corrected timezone as a suggestion
(slice 6). The development sample cannot exercise this rule; tests use a deliberately
shifted derivative (sample-corpus §7).

---

## 8. Reconciliation — `REC.*`

**v1, slice 6.** Only when both frequencies exist for the same contract. Aggregate minute
records into daily bars (`specs/analytics-semantics.md`), join to vendor daily bars on
`(contract_id, session_date)`, compare field by field. This is the only family that can
catch data that is internally perfect and still wrong.

Session date is **derived** on the configured boundary, never read from a vendor column
(same reason as `CON.WEEKEND_RECORD`).

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `REC.OHLC_DISAGREE` | error | session | Derived `open`, `high` or `low` differs from the vendor's by more than `params.tolerance_ticks`. `details.field` names it. |
| `REC.VOLUME_SHORTFALL` | warning | session | Minute-sum volume is below vendor daily volume by more than `params.max_shortfall_pct`. Shortfall only; excess does not fire. |
| `REC.SESSION_ONLY_IN_ONE` | warning | session | A session exists at one frequency and not the other, inside the reconcilable window. |
| `REC.CLOSE_CONVENTION` | info | session | The two closes differ in the manner expected of a settlement versus a last trade. |

Storage: same `dq.dq_finding` table, with `frequency` + `compare_frequency`
(`specs/data-model.md` §4).

### 8.1 Coverage-gated invariant

On any session where the minute data holds at least `params.min_coverage_pct` of the
**calendar** expected slots (`expected_slots_1m`, not a max inferred from the upload):

> `vendor_high >= derived_high` and `vendor_low <= derived_low` and
> `vendor_volume >= minute_sum_volume`.

Gate on calendar expected slots. A violation means (in decreasing likelihood) a wrong
session boundary, a coverage gate that admitted an incomplete session, or a defective
vendor daily row. Assert this invariant in tests, not an agreement percentage. Oracle
claims and the 654-session rates: `specs/sample-corpus.md` §6.

### 8.2 Tolerances

Expressed **in ticks, never in absolute price**, using the same `(root, frequency, field)`
tick as `VAL.OFF_TICK_PRICE`. Where no tick is known, `REC.OHLC_DISAGREE` compares exactly
and says so on the finding.

| Parameter | Default | Reason |
|---|---|---|
| `tolerance_ticks` | 0 | Open/high/low are selections from the same prints; exact equality is the expectation. Non-zero only for a vendor known to round. |
| `min_coverage_pct` | 0.98 | Below this the comparison is not meaningful and the invariant does not hold. |
| `max_shortfall_pct` | 0.10 | Measured tape share is about 95%; 10% leaves headroom without hiding a real gap. |
| `close_convention_ticks` | 1 | Above one tick of difference, treat the close gap as a convention difference worth reporting. |

### 8.3 Volume, one direction

`REC.VOLUME_SHORTFALL` fires only when the minute sum falls short. Vendor volume
legitimately exceeds the tape (block / privately negotiated trades; roll dates where volume
trades as calendar spreads). Excess is a statistic on the reconciliation summary, not a
finding.

### 8.4 Close as information

`REC.CLOSE_CONVENTION` stays `info`. It must not enter the score numerator. Auto-excluding
on it would discard the daily config for a convention difference that is not an error.

Fire when the closes differ by more than `close_convention_ticks` **and** the vendor close
sits nearer the settlement mark than the session end. When they differ and that signature is
absent, the finding is `REC.OHLC_DISAGREE` on `close`. The settlement mark is per-root
configuration, seeded and overridable.

### 8.5 Reconcilable window

`REC.SESSION_ONLY_IN_ONE` is restricted to the intersection of the two date spans, further
restricted to the completeness liquidity window.

- **Minute session with no daily row** — the interesting direction. `warning`.
- **Daily row with no minute session** — deferred-contract case. Suppress inside
  suppression windows; `info` outside them.

Outside the reconcilable window, absence at one frequency is not a finding.

### 8.6 Sub-score

```
reconciliation = 100 × (1 − reconciliation_defect_sessions / reconcilable_sessions)
```

Denominator: sessions present at both frequencies and inside the reconcilable window, not
records. `REC.CLOSE_CONVENTION` never enters the numerator. A contract with no reconcilable
sessions has **no** reconciliation score — not 100, not 0. Reconciliation rows in
`mart.dq_metric_daily` are absent, not zero, when only one granularity was uploaded.

---

## 9. Roll and expiry — `ROL.*`

Exist to *reduce* noise. Without them the last two weeks of every contract generate
completeness alerts for normal market behaviour. Dimension `completeness`; both `info`.

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `ROL.THIN_NEAR_EXPIRY` | info | series | Volume collapse within `params.days` of expiry. Suppresses completeness alerts in that window. |
| `ROL.NO_SUCCESSOR` | info | series | Front month approaching expiry with no deferred contract present in the corpus. |

---

## 10. Outliers — `OUT.*`

**v1 optional.** Method in `specs/analytics-semantics.md`. Always `info`, never
auto-excluded (locked with the cleaning policy). Dimension `validity`.

| Code | Severity | Scope | Trigger |
|---|---|---|---|
| `OUT.RETURN_MAD` | info | record | Modified z-score on log returns exceeds `params.threshold` (default 3.5). |
| `OUT.VOLUME_MAD` | info | record | Modified z-score on log volume exceeds threshold. |

---

## 11. The DQ score

Displayed on every persona dashboard. The definition is shown in the UI (tooltip).

### 11.1 Per-dimension sub-score

Each dimension yields 0–100 over a slice (contract × date range × frequency, except
reconciliation which is session-grained and `frequency = 'cross'`):

```
completeness = 100 × min(1, actual_records / expected_records)
uniqueness   = 100 × (1 − duplicate_records    / actual_records)
validity     = 100 × (1 − invalid_records      / actual_records)
consistency  = 100 × (1 − inconsistent_records / actual_records)
timeliness   = 100 × (1 − untimely_records     / actual_records)

reconciliation = 100 × (1 − defect_sessions / reconcilable_sessions)   -- when defined
```

Completeness uses `expected_records` (after suppressions) because it is the only dimension
that can detect something not in the table. If `expected_records` is 0, completeness is out
of scope for that slice, not a score of 100.

Count each record **at most once per dimension**, not once per finding. Only findings of
severity `warning`, `error`, or `critical` count as defects; `info` does not.

### 11.2 Overall score

Weighted mean of the dimensions **in scope**:

```
overall = Σ(wᵈ × scoreᵈ) / Σ(wᵈ)     for d in dimensions_in_scope
```

Default weights, stored in config, not code:

| Dimension | Weight | Reason |
|---|---|---|
| Completeness | 0.30 | Missing data is the hardest to work around |
| Validity | 0.25 | Corrupt values silently poison analytics |
| Consistency | 0.20 | Usually indicates a systemic feed problem |
| Uniqueness | 0.15 | Real but mechanically fixable |
| Timeliness | 0.10 | Often benign ordering noise |
| Reconciliation | 0.20 | Conditional. Only enters the sum when defined |

### 11.3 Conditional dimension: renormalise

Reconciliation cannot have a fixed weight in a fixed-denominator formula. Scoring a
contract down (or up) because the user uploaded one file rather than two is indefensible.

Rejected alternatives: absent dimension scores 100 (rewards uploading less); scores 0
(punishes uploading less as if the data were broken); dropped from the numerator only
(silent different maxima). Reporting reconciliation separately and keeping a five-dimension
composite is the fallback if renormalisation confuses the UI, but it hides the strongest
evidence from the number people look at.

**Rule: renormalise over dimensions in scope.** A contract with both frequencies divides by
1.20; a contract with one divides by 1.00. Each score is a weighted mean over exactly the
evidence available, on a 0–100 scale. Relative weight order is preserved.

A six-dimension score is better evidenced than a five-dimension score; it is not the same
measurement. Two requirements follow.

**The score object carries the scope.** Every score states which dimensions were in scope,
why any were not, the weight actually applied, and the denominator it was renormalised by.

```json
{
  "overall": 96.4,
  "dimensions_in_scope": ["completeness", "uniqueness", "validity", "consistency", "timeliness"],
  "dimensions_not_in_scope": [
    { "dimension": "reconciliation", "reason": "only one frequency uploaded for this contract" }
  ],
  "scope_signature": "cmp+val+con+unq+tim",
  "weight_denominator": 1.00,
  "dimensions": {
    "completeness": { "score": 94.2, "weight": 0.30, "denominator": 1380, "basis": "expected_records" }
  }
}
```

HTTP envelopes for this object are owned by `specs/api-contract.md` when promoted; the
fields above are the semantic contract.

**The UI must not rank across scopes without saying so.** Any list that sorts by overall
score marks which rows were scored over which dimension set, and offers a "compare like
with like" toggle restricted to the intersection of scopes. Sorting a mixed list is
legitimate for triage; presenting the two as equivalent measurements is not.

The 0.20 reconciliation weight sits between validity and consistency. Evidence is stronger
than either (external rather than self-referential) but available for a minority of
contracts and scored per session; a dominant weight would swing one contract on a dimension
its neighbour does not have.

### 11.4 Honest use

- Always show the breakdown. The composite is navigation; the per-dimension scores are the answer.
- Show the formula in a tooltip.
- State the denominator ("94.2 over 1,380 expected records").
- State the scope.
- Below `params.min_records` (default 100), show "insufficient data" instead of a score.
- Call it an index, not a probability.

---

## 12. Recurring patterns

**v1, slice 6.** Search for over-concentration of findings along:

| Dimension | Pattern it exposes |
|---|---|
| Hour of day (exchange local) | Session-boundary or maintenance-window artefacts |
| Day of week | Weekend handling, Monday-open effects |
| Trade date | One-off outages |
| Contract | A single bad instrument, or a roll artefact |
| Field | One column systematically broken |
| Frequency | A defect that belongs to one granularity of the same contract |
| Batch / source file | A bad vendor delivery |
| Rule | Which single defect dominates |

`frequency` is required: the same contract behaves differently at the two granularities
(sample-corpus §7.3). Without it, a settlement-close pattern is attributed to a contract or
field, and the suggestion proposes the wrong fix.

Detection is deterministic: for each `(rule_id, dimension, bucket)`, compare the bucket's
share of findings to its share of records. Report when
`share_of_findings >= params.lift × share_of_records` (default lift 3.0) with at least
`params.min_support` findings (default 20). Require recurrence across at least
`params.min_periods` distinct days. Correct for exposure — the ratio matters, not the raw
count.

```json
{
  "pattern_id": "p_01H...",
  "rule_id": "CMP.MISSING_TIMESTAMP",
  "dimension": "hour_of_day",
  "bucket": "16:00-17:00 America/Chicago",
  "share_of_findings": 0.82,
  "share_of_records": 0.04,
  "lift": 20.5,
  "support": 412,
  "distinct_days": 61,
  "narrative": "82% of missing-timestamp findings for ESZ25 fall in the 16:00-17:00 CT hour, across 61 of 63 sessions.",
  "confidence": "high"
}
```

`narrative` is generated from a template, not a language model. Aggregates only; raw market
data never leaves the process (locked decision 5).

---

## 13. Suggestions

**v1 is report-only** (locked decision 10). Apply → mutate `dq.dq_rule` / calendar → re-run
in the same request is an **extension**, as is finding override. v1 still shows rationale
and `expected_effect`. `expected_effect` is computed by dry-running the proposed change
before display.

Deterministic generators, each triggered by a pattern:

| Trigger pattern | Suggestion |
|---|---|
| Gaps concentrated in a fixed daily hour | Add a halt window to the calendar |
| Whole sessions missing on dates matching a known holiday list | Add holiday calendar entries |
| Activity dead zone offset by a whole number of hours | Correct the source timezone and reprocess |
| High `UNQ.KEY_CONFLICT` rate from one file | Adopt a dedupe tie-break policy for that source |
| Off-tick prices concentrated in one field of one frequency | Correct the tick reference for that `(root, frequency, field)`, or mark the field settlement-bearing |
| Outlier prices clustering at exactly 10× or 100× | Add a decimal-shift correction rule |
| Same field null in a fixed source column | Revise the column mapping |
| Gaps concentrated in the final days before expiry | Suppress completeness checks in the roll window |
| `REC.CLOSE_CONVENTION` on nearly every reconcilable session | Record the vendor close as a settlement on the batch and stop comparing it to a last trade |
| `REC.VOLUME_SHORTFALL` concentrated on roll dates | Suppress the shortfall check on roll dates |

Worked example — prefer this over an injected defect in the demo: VX daily `close` off-tick
on 805 of 959 rows, zero of 373,886 VX minute rows, every finding in `close`
(sample-corpus §7.3). The applicable fix is to mark `(VX, daily, close)` settlement-bearing
and exempt it.

```json
{
  "suggestion_id": "s_01H...",
  "from_pattern": "p_01H...",
  "kind": "calendar",
  "title": "Suppress the 16:00-17:00 CT maintenance break for ES",
  "rationale": "412 missing-timestamp findings across 61 sessions fall entirely within the CME daily maintenance break, when no trading occurs.",
  "evidence": { "findings": 412, "sessions": 61, "lift": 20.5 },
  "proposed_change": {
    "target": "ref.session_calendar",
    "operation": "add_halt_window",
    "params": { "root": "ES", "start_local": "16:00:00", "end_local": "17:00:00" }
  },
  "expected_effect": { "findings_suppressed": 412, "completeness_delta_pct": 4.1 },
  "confidence": 0.95,
  "actions": ["apply", "dismiss"]
}
```

In v1 the `actions` are not wired. **Extension** if asked: a `narrative` generator that
rewrites the templated explanation in richer prose, taking only aggregated pattern
statistics — never raw market data.

---

## 14. Default cleaning policy

Joint with `specs/data-model.md` §4.1. Severity mapping in §1 is the general rule; this
table names the coded actions.

| Rule | Action |
|---|---|
| `UNQ.EXACT_DUPLICATE` | `dedupe_drop`, keep lowest `source_row` |
| `UNQ.KEY_CONFLICT` | `exclude` all conflicting rows |
| `CON.HIGH_LT_LOW` | `exclude` |
| `CON.OPEN_OUT_OF_RANGE` | `exclude` |
| `CON.CLOSE_OUT_OF_RANGE` | `exclude` |
| `VAL.NON_POSITIVE_PRICE` | `exclude` |
| `VAL.NEGATIVE_VOLUME` | `exclude` |
| `CMP.NULL_FIELD` | `exclude` |
| `VAL.OFF_TICK_PRICE` | flag only |
| `OUT.*` | flag only, never exclude |
| `CON.DERIVED_BAR_INVALID` (vendor) | flag only |
| `CON.DERIVED_BAR_INVALID` (derived) | exclude + block series |

---

## 15. Fixtures

Tiny committed CSVs under `tests/fixtures/`, one planted defect per file, so a failing test
names the rule it broke. Real corpus files are not unit fixtures (sample-corpus §8).

**Naming.** `tests/fixtures/<rule_id_lower>.csv` with `.` → `_` (`val_off_tick_price.csv`).
Negative cases (must not fire) use a suffix: `con_weekend_record_sunday_evening.csv`.

Slice 1 already owns ingest fixtures (`unparseable.csv` → `STR.UNPARSEABLE_ROW` /
`STR.BAD_TIMESTAMP`; `null_fields.csv` is a *load* of nullable OHLCV, not `CMP.NULL_FIELD`
until slice 2 writes findings; `weekend_sunday_evening.csv` is the negative case for
`CON.WEEKEND_RECORD`). Slice 2 adds one fixture and unit test per core rule ID below.
`REC.*` fixtures wait for slice 6. `TIM.TIMEZONE_MISALIGNED` and remaining `STR.*` use
deliberately corrupted derivatives, not the pristine sample.

### 15.1 v1 core rule IDs (slice 2)

`CMP.NULL_FIELD`, `CMP.MISSING_TIMESTAMP`, `CMP.SESSION_MISSING`, `CMP.PARTIAL_SESSION`,
`CMP.SPARSE_SERIES`, `UNQ.EXACT_DUPLICATE`, `UNQ.KEY_CONFLICT`, `VAL.NON_POSITIVE_PRICE`,
`VAL.NEGATIVE_VOLUME`, `VAL.NON_INTEGER_VOLUME`, `VAL.OFF_TICK_PRICE`,
`VAL.ZERO_VOLUME_WITH_RANGE`, `VAL.PRICE_MAGNITUDE`, `VAL.EXTREME_VOLUME`,
`CON.HIGH_LT_LOW`, `CON.OPEN_OUT_OF_RANGE`, `CON.CLOSE_OUT_OF_RANGE`,
`CON.WEEKEND_RECORD`, `CON.RECORD_IN_HALT`, `CON.RECORD_ON_HOLIDAY`, `CON.STALE_REPEAT`,
`CON.PRICE_JUMP`, `CON.DERIVED_BAR_INVALID`, `TIM.OUT_OF_ORDER`, `TIM.FUTURE_TIMESTAMP`,
`TIM.BEFORE_LISTING`, `TIM.AFTER_EXPIRY`, `TIM.OFF_GRID`, `TIM.TIMEZONE_MISALIGNED`,
`ROL.THIN_NEAR_EXPIRY`, `ROL.NO_SUCCESSOR`. Optional: `OUT.RETURN_MAD`, `OUT.VOLUME_MAD`.
`UNQ.DUPLICATE_FILE` is covered by ingest tests (`DuplicateFileError`); no finding fixture
required.

### 15.2 Solution-brief §13 edges

| Edge | Rule ID |
|---|---|
| Exact dup | `UNQ.EXACT_DUPLICATE` |
| Key conflict | `UNQ.KEY_CONFLICT` |
| Mid-session gap | `CMP.MISSING_TIMESTAMP` |
| Missing day | `CMP.SESSION_MISSING` |
| Negative volume | `VAL.NEGATIVE_VOLUME` |
| `high < low` | `CON.HIGH_LT_LOW` |
| Close outside range | `CON.CLOSE_OUT_OF_RANGE` |
| Unparseable timestamp | `STR.BAD_TIMESTAMP` (ingest) |
| Empty / missing header | `STR.MISSING_REQUIRED_COLUMN` (ingest) |
| Sunday-evening trade date | `CON.WEEKEND_RECORD` must **not** fire on the derived session date |
| Three-character root (`SR3`) | symbology / ingest, not a DQ rule (`sr3_symbol.csv`) |
| Off-tick settlement | `VAL.OFF_TICK_PRICE` |
| Timezone smear | `TIM.TIMEZONE_MISALIGNED` |

Property checks (slice 2): cleaning is idempotent; per-dimension defect counts do not
double-count a record; overall is the renormalised weighted mean of dimensions in scope.

---

## 16. Calibration rates

Measured baselines that justify seeded defaults live in `specs/sample-corpus.md` §7. They
are **baselines, not live alert thresholds**. They describe one vendor. A zero is a result
(tick inference and epsilon held on 5.3 million minute rows), not an absence of a run.
