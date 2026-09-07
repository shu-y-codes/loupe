# Loupe — DQ rules and scoring

**Normative.** Rule catalogue, severities, score formula, pattern and suggestion shapes, and
the fixture-to-rule mapping. Promoted from research `_notes/cursor/04-dq-rules-and-scoring.md`
(now archaeology). Summary and v1 boundary: `specs/loupe-solution-design.md` §9. Storage:
`specs/data-model.md` §4. Sample rates used as calibration: `specs/sample-corpus.md` §7.
Session grid, bar provenance and MAD method: `specs/analytics-semantics.md`.

Revised 2026-09-07: the reviewer page does not draw a score (`specs/loupe-ui-design.md`);
§11.3 still applies when a score is displayed. Same day: reviewer-strip family set (§11.8);
drop persona-dashboard sentences. The score formula and rule triggers are unchanged.

Revised 2026-09-05: promoted from research; first normative version. Same day: `dq.dq_rule.weight`
renamed `triage_weight` and defined as worklist ordering only (§11.4) — it had no role in any
score formula and the name invited one. Same day: §15 notes that `CON.DERIVED_BAR_INVALID` and
`OUT.*` remain v1 core IDs while plans defer their fixtures to slice 3. Same day:
`CON.CLOSE_OUT_OF_RANGE` severity follows the bar interval (§6, §14) — a daily close is a
settlement, so it drops to `params.daily_severity` and is explained on the bar rather than
excluded from it.

**Scope of authority.** This spec owns *rule IDs, triggers, params, cleaning consequences, the
score, and the fixture map*. It does not own DDL, sample measurements, or HTTP envelopes
(`specs/api-contract.md`). Every v1 core rule ID seeds a row in `dq.dq_rule`
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
systematic; `CON.DERIVED_BAR_INVALID` severity follows bar provenance;
`CON.CLOSE_OUT_OF_RANGE` severity follows the bar interval, because a daily close is a
settlement). Policy lives in
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
| `CON.CLOSE_OUT_OF_RANGE` | error intraday, `params.daily_severity` daily | record | `close` outside `[low, high]`. |
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

**`CON.CLOSE_OUT_OF_RANGE` severity follows the bar interval,** for the same reason
`VAL.ZERO_VOLUME_WITH_RANGE` does and asked the same way — of
`stage.ingest_batch.bar_interval`, not of `frequency = 'daily'`. An intraday close is a
trade and must sit inside the session's range. A daily close is a **settlement**, struck by
the exchange and under no obligation to sit inside the traded range: on this corpus all 43
such rows are untraded deferred contracts carrying a prior mark (sample-corpus §7.5).
Default params `{"daily_severity": "warning"}` — below `error`, so default cleaning does not
exclude, the vendor bar reaches `mart.bar_daily`, and `CON.DERIVED_BAR_INVALID` explains it
there. A null `daily_severity` falls back to the declared `error` rather than disabling the
daily branch: a close outside its range is always reportable, and what the param configures
is whether it is excludable.

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

**Which side goes in `frequency`.** `frequency` is the side the finding is a *statement
about*; `compare_frequency` is the side it was checked against. This is not free-form: the
closing-day callout selects `SETTLEMENT_RULES` at `frequency = 'daily'` (§11.6), so a
reconciliation finding written on the wrong side is filtered out silently rather than
rejected. The convention follows each rule's own claim:

| Rule | `frequency` | Because |
|---|---|---|
| `REC.OHLC_DISAGREE` | `daily` | it says the vendor's stated `high` or `low` is wrong |
| `REC.CLOSE_CONVENTION` | `daily` | its subject is the settlement |
| `REC.VOLUME_SHORTFALL` | `minute` | it says the *tape* is short — which is why §8.3 fires in one direction only |
| `REC.SESSION_ONLY_IN_ONE` | the side that holds the session | it is a statement about the side that has it |

`'cross'` is **not** a finding's frequency. It is the `mart.dq_metric_daily` rollup grain for
the reconciliation dimension (§11.1), where the row is about the pair rather than either
side.

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

### 8.7 Corroboration — what reconciliation does for a daily finding

Reconciliation's value for a daily finding is **attribution, not detection**. A daily defect is
already visible in the daily file; what a single file cannot say is *which of its numbers to
distrust*.

`CON.CLOSE_OUT_OF_RANGE` is the worked example. On its own it says four numbers from one row do
not cohere — close above high, or below low. Two situations produce it and they call for
opposite responses:

- **The range is right and the close sits outside it.** Vendor `open`/`high`/`low` agree with
  the tape, so the traded range is correctly measured. A settlement is not a trade: it is
  derived from a closing range or set by committee and is under no obligation to fall inside
  the day's prints. This is ordinary behaviour, and it is why the rule drops to
  `params.daily_severity` at daily grain (§6) rather than excluding the row.
- **The range is understated.** `REC.OHLC_DISAGREE` fires on `high` or `low` for the same
  session: the tape found prints outside the vendor's stated range. The *range* is the broken
  field, and the close may be sound. Without the tape this is invisible and the reader reaches
  for the close.

So a daily finding on a contract that also holds minute records carries a **corroboration
state**, and there are three of them — the same three-way shape as the publication gate,
because collapsing "we checked and it holds" into "we could not check" is the failure both
exist to prevent:

| State | When | What it licenses |
|---|---|---|
| `confirmed` | The session is inside the reconcilable window, minute coverage is at or above `min_coverage_pct`, and no `REC.OHLC_DISAGREE` fired on it | The range is measured correctly; the finding is about the close |
| `disputed` | `REC.OHLC_DISAGREE` fired on `high` or `low` for that session | The stated range is wrong; re-read the finding as a range defect |
| `not_comparable` | One granularity only, outside the reconcilable window (§8.5), or coverage below `min_coverage_pct` | Nothing. Say so rather than implying either of the above |

**Corroboration is not a rule and writes no finding.** It is a reading of findings that already
exist, composed in `quality` and carried alongside a finding so the UI can state it (see
`specs/loupe-ui-design.md`, Specifics). It enters no score: §8.6's numerator is unchanged.

It therefore gets its own module — `src/loupe/quality/corroboration.py` — rather than joining
the rule runners or the scorer. It is neither: a runner writes findings and a scorer produces
numbers, and this does neither. Filing it with either would invite a later contributor to make
it do the thing its neighbours do.

**It travels on the finding.** `specs/api-contract.md` §6.2 carries it as a `corroboration`
object on each finding rather than on a route of its own, because it qualifies *that finding*
and a separate endpoint would let a client render the finding without it. The envelope adds a
fourth answer the three states above do not need: `corroboration` is **absent** on findings
this reading does not apply to — a minute-grain timeliness finding is not a claim the daily
file can speak to — where `not_comparable` means it applies but could not be evaluated.

**What it does not do.** It cannot adjudicate the settlement itself. A legitimately different
settlement and an erroneous one look identical to `REC.CLOSE_CONVENTION`, which is why that
rule is `info` and stays out of the numerator (§8.4). Corroboration confirms or disputes the
*range*, quantifies the gap, and — via `REC.VOLUME_SHORTFALL` — says whether the tape was
complete enough for either statement to carry weight.

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

Displayed wherever a score appears. `scope_signature` is required **when a score is
displayed** (§11.3). The reviewer page does not draw a score; chrome is
`specs/loupe-ui-design.md`.

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

Default weights, seeded into `dq.score_weight` (one row per dimension) and read at scoring
time — never literals in the scorer. This is the only weights table in the score;
`dq.dq_rule.triage_weight` is not an input (§11.4):

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

HTTP envelopes for this object are owned by `specs/api-contract.md`; the fields above are
the semantic contract.

**The UI must not rank across scopes without saying so.** Any list that sorts by overall
score marks which rows were scored over which dimension set, and offers a "compare like
with like" toggle restricted to the intersection of scopes. Sorting a mixed list is
legitimate for triage; presenting the two as equivalent measurements is not.

The 0.20 reconciliation weight sits between validity and consistency. Evidence is stronger
than either (external rather than self-referential) but available for a minority of
contracts and scored per session; a dominant weight would swing one contract on a dimension
its neighbour does not have.

### 11.4 Rule triage weight — ordering, not scoring

`dq.dq_rule.triage_weight` answers a different question from the score. The score says *how
good is this data*; triage weight helps answer *what should I fix first*. It **never enters
any score formula** — §11.1 counts records, at most once per dimension, and a per-rule
multiplier there would double-count a record two rules both fired on.

Seeded from severity, so the ordering is sensible before anyone tunes it and the number
means something a business user can state out loud ("one critical outranks two errors"):

| Severity | `triage_weight` |
|---|---|
| `critical` | 8.0 |
| `error` | 4.0 |
| `warning` | 2.0 |
| `info` | 0.5 |

Overridable per rule, per deployment. A desk that cannot act on off-tick prices sets
`VAL.OFF_TICK_PRICE` low and stops seeing it at the top of the list; the score does not move,
because nothing about the data changed.

**Worklist rank** = `triage_weight × affected_records`, within a slice. Show the two factors
alongside the product — a business user must be able to see whether a row is high because the
defect is bad or because it is everywhere.

**The headline guide is computed, not configured.** For each rule with open findings, state
what resolving it would do to the score it feeds:

```json
{
  "rule_id": "CMP.MISSING_TIMESTAMP",
  "dimension": "completeness",
  "affected_records": 412,
  "triage_weight": 2.0,
  "rank": 824.0,
  "score_if_resolved": { "completeness": 97.8, "overall": 96.4, "from": { "completeness": 94.2, "overall": 95.1 } }
}
```

`score_if_resolved` is §11.1 recomputed with that rule's defect count set to zero — the same
dry-run mechanism as `expected_effect` on a suggestion (§13). It is the number to lead with:
it is derived from the data rather than from a dial someone set, and it is denominated in the
units the dashboard already shows. Triage weight breaks ties and orders rules whose score
impact is comparable.

Do not present rank as a severity, a probability, or a currency amount.

### 11.5 Honest use

**Interpretation:** The overall score is a 0–100 quality index where higher is better. A score
of 96.4 means high data quality; a score of 50 means moderate issues and significant
attention is warranted; 0 is worst possible. The score is a **navigation tool**, not a
grade — it points the user to which dimensions need work, so show the breakdown first.

- Always show the breakdown. The composite is navigation; the per-dimension scores are the answer.
- Show the formula in a tooltip.
- State the denominator ("94.2 over 1,380 expected records").
- State the scope.
- Below `params.min_records` (default 100), show "insufficient data" instead of a score.
- Call it an index, not a probability or a grade.

### 11.6 Settlement rules — a callout filter, not a score input

Like §11.4's triage weight, this classifies rules for a presentation purpose and enters no
score formula. `SETTLEMENT_RULES` selects findings whose subject can be the session's
*settlement* record, not the contract's worst issue of any kind, and nothing on `dq.dq_rule`
distinguishes the two. `/v1/dq/summary` still ships `settlement_issue` from this set. The
reviewer page (`specs/loupe-ui-design.md`) does **not** have a Closing-day column. The named
set is:

| Rule | The closing-day statement it makes |
|---|---|
| `CON.CLOSE_OUT_OF_RANGE` | close outside H–L |
| `CMP.SESSION_MISSING` | missing EOD bar |
| `UNQ.KEY_CONFLICT` | duplicate settlement |
| `VAL.OFF_TICK_PRICE` | off-tick close |

The set is closed at those four. It is a list of defects in a settlement, not a list of
everything that mentions one.

Membership test: the rule's subject can be the session's settlement record, **and the rule
asserts a defect**.

**No `REC.*` rule joins this set, `REC.CLOSE_CONVENTION` included.** An earlier draft of this
section said slice 6 would add it, on the grounds that its subject is plainly the settlement.
That was wrong on the second half of the test. It is `info`, it fires on the *expected*
difference between a settlement and a last trade (§8.4), and `settlement_issue` is what is
*wrong* with a settlement. Filling it with a difference that is not an error is noise.

Reconciliation's contribution is not another settlement callout. It is the corroboration
state of §8.7, which changes what an existing finding **means** — whether a close outside the
range sits outside a confirmed range or a disputed one. That rides on the finding
(`specs/api-contract.md` §6.2), not as a book-grain column.

**Filtered to `frequency = 'daily'` findings**, which is load-bearing rather than tidying.
`VAL.OFF_TICK_PRICE` on a minute record says "off-tick price", not "off-tick close" — §5
makes the lattice a property of `(root, frequency, field)` precisely because a settlement is
under no obligation to sit on the tick. `CMP.SESSION_MISSING` is a settlement statement only
at daily grain: one daily record per session *is* the settlement, so its absence is a missing
settlement, whereas the same finding at minute grain means "no tape at all". Without the
clause the column fills with intraday noise that is not about the close.

**Consequence, and accepted:** a contract held only at minute grain gets no closing-day
callout when its close is missing. That shortfall surfaces as `CMP.MISSING_TIMESTAMP` or
`CMP.PARTIAL_SESSION`, neither of which is in the set. This is the intended reading, not a
gap to patch — settlement comes from the daily file. The contract still appears in
`/v1/dq/summary` with its score and `top_issue`; `settlement_issue` is null.

**`UNQ.EXACT_DUPLICATE` is deliberately out**, though at daily grain it is also literally a
duplicated settlement row. It is auto-resolved by `dedupe_drop` keeping the lowest
`source_row` (§14), so it is a changelog entry rather than open settlement risk. A key
conflict is the opposite: two *different* settlement prices for one session with no
principled winner inside the file, which is exactly what `settlement_issue` must name.

The set lives beside `DEDUPE_DROP_RULES` and `NEVER_EXCLUDE_RULES` in
`src/loupe/quality/catalogue.py`, which is already where a named set of rule IDs with a
documented reason belongs.

### 11.7 Rule subject field — from rule identity

`worst_field` on `/v1/dq/summary` names the field most findings implicate — "close",
"timestamp". It is derived from **rule identity**, never by grouping `dq.dq_finding.details`:
that column is evidence and is explicitly never grouped on (`specs/data-model.md`), and a JSON
payload is the wrong key for an aggregate. Like §11.4 and §11.6, this enters no score formula.
The reviewer page does not show a worst-field tile.

**Membership is a two-part test**, because the tile answers *what is broken*: the rule must
**assert a defect**, and must **fix the field that defect is in**. "Fixes a field" alone is
too loose — it admits rules that name a field while claiming nothing is wrong with it.

`RULE_SUBJECT_FIELD`:

| Field | Rules |
|---|---|
| `close` | `CON.CLOSE_OUT_OF_RANGE` |
| `open` | `CON.OPEN_OUT_OF_RANGE` |
| `volume` | `VAL.NEGATIVE_VOLUME`, `VAL.NON_INTEGER_VOLUME`, `VAL.ZERO_VOLUME_WITH_RANGE`, `VAL.EXTREME_VOLUME` |
| `timestamp` | all `TIM.*`, `CON.WEEKEND_RECORD`, `CON.RECORD_IN_HALT`, `CON.RECORD_ON_HOLIDAY` |

The `timestamp` row is the one to read carefully: every rule in it fires on a record that
**exists** and whose timestamp is wrong — off the grid, out of order, misaligned, or placing
the record on a weekend, holiday or halt. That is what separates it from the absence rules
below.

**Rules absent from the map do not contribute to the tile, and that is the point.** Three
kinds are absent:

- **Field-parametric** — `CMP.NULL_FIELD`, `VAL.NON_POSITIVE_PRICE`, `VAL.OFF_TICK_PRICE`,
  `VAL.PRICE_MAGNITUDE`, `CON.HIGH_LT_LOW`, `CON.PRICE_JUMP`. Which field they implicate is
  known only per finding, in `details`. Reading it there to feed an aggregate is the thing
  this section exists to prevent, so they are excluded rather than guessed at.
- **Record-, session- or series-shaped** — all `UNQ.*`, `CMP.MISSING_TIMESTAMP`,
  `CMP.SESSION_MISSING`, `CMP.PARTIAL_SESSION`, `CMP.SPARSE_SERIES`, `CON.STALE_REPEAT`,
  `CON.DERIVED_BAR_INVALID`, all `ROL.*`. Their subject is a row, a session or a contract,
  not a field; "worst field" is not a question they answer.

  `CMP.MISSING_TIMESTAMP` belongs **here, not under `timestamp`**, and the whole family
  makes the point: its trigger is a run of expected slots with *no record*, so there is no
  timestamp value that is wrong — the defect is absence. It is `CMP.SESSION_MISSING` and
  `CMP.PARTIAL_SESSION` at a different span, and the three are treated alike.
- **Diagnostic rather than defect** — `OUT.RETURN_MAD`, `OUT.VOLUME_MAD`. §10 makes `OUT.*`
  always `info` and never auto-excluded: they say a value is *unusual*, not that it is
  *wrong*, and the tile would be counting findings that assert nothing is broken. The field
  attribution is also weaker than it looks — a log return spans two closes, so no individual
  close is accused. Outliers are the most numerous thing in a volatile window, so admitting
  them would let a diagnostic dominate a defect tile.

Slice 6's `REC.*` join under the same two-part test: volume shortfall is `volume` and
asserts a defect; session-only-in-one is record-shaped and therefore absent; the
close-convention rule is **absent** — §8.4 keeps `REC.CLOSE_CONVENTION` at `info` and out of
the score numerator, so it is a diagnostic and fails the first half of the test even though
its field is plainly `close`.

The tile shows the field with the most findings among mapped rules, and reads "not
applicable" — not a fabricated field — when a scope's findings are entirely from unmapped
rules. `RULE_SUBJECT_FIELD` lives in `src/loupe/quality/catalogue.py` beside
`SETTLEMENT_RULES`.

### 11.8 Reviewer strip families

Labelling for the four cards on the reviewer page. Enters no score formula and does not
change rule triggers. Catalogue sets live beside `SETTLEMENT_RULES` in
`src/loupe/quality/catalogue.py`. Overlay join: `specs/api-contract.md` §6.6;
chrome: `specs/loupe-ui-design.md`.

| Family | Rule IDs | Off this card |
|---|---|---|
| `gaps` | `CMP.MISSING_TIMESTAMP`, `CMP.SESSION_MISSING`, `CMP.PARTIAL_SESSION` | `CMP.NULL_FIELD` |
| `duplicates` | `UNQ.EXACT_DUPLICATE`, `UNQ.KEY_CONFLICT` | `UNQ.DUPLICATE_FILE` (ingest list) |
| `invalid` | all `VAL.*`, `CMP.NULL_FIELD`, `CON.HIGH_LT_LOW`, `CON.OPEN_OUT_OF_RANGE`, `CON.CLOSE_OUT_OF_RANGE` | `OUT.*` |
| Recurring patterns | not a rule family — standing rows from pattern lift (§12) | a count of findings as the lead |

Every catalogue rule is in exactly one of `gaps`, `duplicates`, `invalid`, or **off-strip**.
Off-strip includes `OUT.*`, remaining `CON.*` / `TIM.*` / `REC.*` / `ROL.*`, `CMP.SPARSE_SERIES`,
and `UNQ.DUPLICATE_FILE`. A card count of zero means the check ran.

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
| `CON.CLOSE_OUT_OF_RANGE` (intraday) | `exclude` |
| `CON.CLOSE_OUT_OF_RANGE` (daily) | flag only at the default `params.daily_severity` — the settlement is explained on the bar by `CON.DERIVED_BAR_INVALID` |
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
`CON.WEEKEND_RECORD`). Slice 2 adds one fixture and unit test per core rule ID below, except
`CON.DERIVED_BAR_INVALID` and the optional `OUT.*` pair, which stay on this list as v1 core
IDs while plans defer their fixtures and runners to slice 3. `REC.*` fixtures wait for slice 6.
`TIM.TIMEZONE_MISALIGNED` and remaining `STR.*` use deliberately corrupted derivatives, not the
pristine sample.

### 15.1 v1 core rule IDs

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

---

## 17. Adding a rule

The v1 workflow, and the reason it is a code change rather than a form. Rules are report-only
(§13): nothing at run time authors a rule, so the catalogue in `src/loupe/quality/` is the only
author and adding one is a deploy. Suggestion **apply** and finding **override** are the
extensions that would change this (`specs/loupe-solution-design.md` §14).

1. **Amend this spec.** A new rule ID, its trigger, severity, scope and params belong in the
   family table (§3–§10), and in §15.1 if it is v1 core. This spec owns rule IDs; deciding the
   trigger here rather than in code is what keeps the two from drifting.
2. **Catalogue entry** — `rule_id`, `dimension`, `name`, `description`, `severity`, `scope`,
   `applies_to_frequency`, `params`, `triage_weight` seeded from severity (§11.4).
3. **Runner**, registered against the `rule_id`, reading its thresholds from the seeded row
   and never from literals.
4. **Fixture and unit test** — `tests/fixtures/<rule_id_lower>.csv`, one planted defect (§15).
   A parity test asserts catalogue IDs, registered runners and the §15.1 in-scope list are the
   same set — less any IDs §15 records as deferred to a later slice — so a half-added rule
   fails the suite rather than seeding a rule that never fires.
5. **Deploy.** The seeder inserts the absent `rule_id`. No DDL change and no migration — a rule
   is a row.
6. **Re-run** over the existing corpus (`dq_run.batch_id` is null for a re-run; no re-ingest).
   The new `ruleset_hash` is what makes the resulting score movement attributable to the rule
   rather than to the data.

**Severity is the high-stakes field, and it is decided at step 1.** §14 maps `error` to
`exclude`, so a new `error` rule does not merely annotate — it removes records from
`dq.market_record_clean` and changes every derived bar and VWAP downstream. Prefer shipping a
new rule as `warning`, observing what it catches on real data, and promoting it to `error` as a
separate, deliberate change. Under this design that promotion is a one-field edit.

This warning-first advice governs rules added **after** the v1 catalogue. The severities in
§3–§10 are already settled and calibrated against the corpus (§16); do not demote one to
`warning` on the strength of this paragraph. The equivalent discipline for the v1 catalogue is
to *measure* what its `error` rules exclude from the real corpus before anything downstream is
built on the clean view — the first exclusion is the one nobody has seen the consequences of.

**A new rule always joins an existing dimension** — the six are fixed. It therefore enters that
dimension's defect count immediately, and adding rules will move a sub-score on unchanged data.
That is correct behaviour, not a bug, and §11.4's `score_if_resolved` plus the run's
`ruleset_hash` are what make it explicable to someone watching the number.

A **threshold change** to an existing rule is the same workflow without steps 3 and 4: edit the
catalogue, deploy, re-seed. The seeder refreshes `origin = 'builtin'` rows, so the corrected
default reaches existing databases.
