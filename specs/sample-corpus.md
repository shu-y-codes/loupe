# Loupe — Sample corpus and oracle

**Normative.** What the development sample contains, what was measured on it, and which of those
measurements other specs and tests may rely on. Promoted from research
`_notes/cursor/06-sample-data.md` (now archaeology). Every figure here is the output of a query
that was executed against the real files.

Revised 2026-09-05: promoted from research; first normative version.

**Scope of authority.** This spec owns *sample and oracle claims*: what the corpus holds, what
the vendor files mean, and the measured baselines. It does not own computation semantics
(`specs/analytics-semantics.md`), rule definitions (`specs/dq-rules-and-scoring.md`) or schema
(`specs/data-model.md`). Where one of those cites a number, the number is owned here.

---

## 1. Provenance and licence

| Field | Value |
|---|---|
| Source | `https://huggingface.co/datasets/lynx1231/historical-futures-data-sample` |
| Revision | last modified 2026-07-30T02:27:54Z |
| Package version | 1.0.0, schema version `public-futures-sample-v1` |
| Generated | 2026-07-30T01:28:56Z, as-of date 2026-07-29 |
| Publisher | Operator of `https://futuresforexandsomeindexes.com`, a commercial market-data vendor |

**Licence — the constraining finding. There is no licence grant anywhere in the package.** The
Hugging Face API `license` field is `null`; `LICENSE`, `LICENSE.txt`, `LICENCE` and `license.md`
all 404 at the repo root; `dataset-metadata.json` says `"licenses": [{"name": "other"}]` with no
text; `SOURCE_NOTICE.md` points at the commercial site and grants nothing.

"Other" with no accompanying text is not permission. The repository is public and ungated, so
downloading it for evaluation is plainly intended, but **nothing authorises redistribution**.

**Consequence, and it is binding.** Vendor files are never committed to this repository.
`data/samples/` and `*.parquet` are gitignored; the corpus is fetched by `tools/fetch_samples.py`
at setup time and is never a runtime dependency of ingest (locked decision 9).

**Integrity.** `checksums.sha256` carries 89 entries; 87 verify. The two failures are `README.md`
and `dataset.json`, documentation files edited after the manifest was generated. **All 82 Parquet
files verify, including all 80 data files.** The fetch script skips the two known-stale
documentation entries rather than reporting a failure the user cannot act on.

**Vendor caveats, both confirmed.**

1. Minute-level source timestamps are integer millisecond labels representing DST-aware
   `America/Chicago` wall-clock values. They are **not true UTC instants**. See §3.
2. Long-dated and deferred contracts may contain settlement-like observations with no reported
   volume and no intrabar price range. Confirmed: 44.11% of daily rows have zero volume.

**Contract selection the publisher declares.** Per root, the newest five contract symbols present
in both configs, listed in both root metadata files, with a delivery month before the as-of
month. Selection uses delivery month rather than last-trade date because exact expiration
specifications are not in the source package — so **the package carries no expiry reference
data**, and `ref.contract.dates_inferred` is true for every contract.

**`files.csv` is a usable reference asset.** One row per Parquet file with `row_count`,
`first_timestamp_ms`, `last_timestamp_ms`, `sha256`, `root`, `month_code`, `delivery_year`,
`delivery_month`, and the diagnostics `source_order_monotonic`, `duplicate_timestamp_count`,
`null_price_row_count`, `invalid_ohlc_row_count`, `no_range_bar_count`. Independent recomputation
agreed with the vendor on `row_count` (80/80 files), `reported_total_volume` (80/80),
`no_range_bar_count` (80/80, read as `open = high = low = close`), and reproduced the same 43
invalid-OHLC rows. Use it to validate symbol parsing rather than trusting the parse.

---

## 2. Structure

Layout is `data/<frequency>/<EXCHANGE>/<ROOT>/<CONTRACT>.parquet`. Eight roots, forty contracts,
and **every one of the forty exists in both configs** — which is what makes the oracle in §5
possible.

| Config | Files | Rows | Size |
|---|---|---|---|
| `data/daily` | 40 | 30,102 | 1.02 MB |
| `data/minute` | 40 | 5,295,239 | 104.53 MB |
| Top-level metadata | 13 | — | 0.08 MB |
| **Total** | **93** | **5,325,341** | **105.62 MB** |

**Six exchanges, not five.** CFE and ICEUS are not CME Group venues, which is why
`ref.contract.exchange` has no default.

| Exchange | Operator | Roots | Product |
|---|---|---|---|
| CBOT | CME Group | ZC, ZN | Corn, 10-Year T-Note |
| CFE | Cboe Global Markets | VX | VIX futures |
| CME | CME Group | ES, SR3 | E-mini S&P 500, Three-Month SOFR |
| COMEX | CME Group | GC | Gold |
| ICEUS | Intercontinental Exchange | SB | Sugar No. 11 |
| NYMEX | CME Group | CL | Crude Oil |

| Root | Exch | Daily rows | Minute rows | Invalid OHLC | Flat minute bars |
|---|---|---|---|---|---|
| CL | NYMEX | 10,310 | 704,287 | 28 | 223,656 (31.8%) |
| ES | CME | 3,505 | 595,430 | 7 | 65,546 (11.0%) |
| GC | COMEX | 3,079 | 380,111 | 0 | 96,178 (25.3%) |
| SB | ICEUS | 3,660 | 676,270 | 0 | 354,069 (52.4%) |
| SR3 | CME | 3,882 | 1,350,500 | 5 | 1,075,602 (79.6%) |
| VX | CFE | 959 | 373,886 | 0 | 156,722 (41.9%) |
| ZC | CBOT | 3,761 | 726,726 | 3 | 418,259 (57.6%) |
| ZN | CBOT | 946 | 488,029 | 0 | 169,570 (34.7%) |

**Vintage: 2021-06-04 to 2026-03-20**, delivery months in 2025 and 2026. There is no 2008-era
data; worked examples in any spec must use real symbols and dates from this range (`ESZ25`,
`SR3M26`, `ZNH26`).

---

## 3. Schemas and column semantics

Read from the Parquet footers. Both configs are lowercase snake_case, and **every column is
physically nullable** in both — though zero nulls are observed anywhere.

**`data/daily` — 12 columns.** `root_id`, `exchange`, `root`, `contract_symbol` (all `string`);
`timestamp_ms` (`int64`); `date` (`date32[day]`); `open`, `high`, `low`, `close` (`double`);
`volume`, `open_interest` (`int64`).

**`data/minute` — 13 columns.** `root_id`, `exchange`, `root`, `contract_symbol` (`string`);
`timestamp_ms` (`int64`); `timestamp_chicago_wall` (`timestamp[ns]`, `isAdjustedToUTC=false`);
`trading_date` (`date32[day]`); `minute_of_day` (`int16`); `open`, `high`, `low`, `close`
(`double`); `volume` (`int64`). **There is no `open_interest` in the minute config.**

### 3.1 Divergence from the exercise's stated columns

The exercise names `Contract, Timestamp, Open, High, Low, Close, Volume`. Two divergences are
more than cosmetic:

- **The timestamp is split across two columns, neither timezone-aware, and the integer is not an
  instant.** `column_mapping` therefore cannot be a flat one-to-one dictionary
  (`specs/data-model.md` §3).
- **The daily `close` is a settlement, not a last trade.** No column mapping can express that; it
  is recorded on the batch as `close_convention`.

`open_interest` (daily only), `exchange`, `root`, `root_id`, `trading_date` and `minute_of_day`
are extra beyond the brief. There is no bid, ask, settlement flag or expiry date.

### 3.2 Contract identity is in a column, and also in the path

Checked exhaustively across all 5,325,341 rows in both configs: `contract_symbol` is populated on
every row and equals the filename stem on every row; `root` equals the parent directory and
`exchange` the grandparent on every row; each of the 80 files holds exactly one distinct
`contract_symbol`.

**Ingestion reads `contract_id` straight from the column** and does not parse the path or take
contract as an upload parameter. The path is a redundant cross-check — disagreement between column
and path is a cheap, high-signal file-level validity rule.

**Symbology is the clean CME form with a two-digit year.** `SR3` is a three-character root, so a
parser assuming two characters of root followed by a month code and year mis-parses a quarter of
the corpus. `SR3M26` splits as root `SR3`, month code `M`, year `26`. `files.csv` supplies `root`,
`month_code`, `delivery_year` and `delivery_month` to validate the parse against.

---

## 4. Timestamps, timezone and sessions

### 4.1 The labels are Chicago wall clock, and `ts_utc` must be derived

`timestamp_ms` read as UTC epoch-milliseconds reproduces `timestamp_chicago_wall` on every row
(595,430 of 595,430 for ES). The integer is a Chicago wall-clock reading encoded through a UTC
epoch function; **treating it as an instant shifts every record by five or six hours.**

The maintenance-break histogram confirms the frame independently. Hour 16 local holds **zero** ES
bars out of 595,430 while every other hour holds 22,923–31,986; at minute resolution the hole is
exactly `minute_of_day` 960–1019 (16:00:00–16:59:00) and no others. That is the CME sixty-minute
maintenance break, sitting at 16:00 in the file's own frame.

**Negative signature, for `TIM.TIMEZONE_MISALIGNED`.** Under a wrong UTC reading the hole does not
move — it splits into two *partial* dips one hour apart (hour 10 at 14,025 bars, hour 11 at
10,853, against neighbours at 24–27k), because the CST and CDT offsets differ and each hour is
partly backfilled by genuine activity. Neither dip reaches zero. **A smeared pair of partial dips
rather than a clean single-hour hole is the fingerprint of a double conversion**, and it is a
better test than noting the hole is in the wrong place.

**The wall clock is genuinely DST-aware.** Implied offset is 300 minutes Apr–Oct (CDT) and 360
minutes Nov–Feb (CST), with both present in the March and November transition months. No label
falls in the non-existent spring-forward hour: 0 of 5,295,239.

**Consequence.** There is no UTC instant in the source at all. `ts_utc` is derived as
`ts_exchange AT TIME ZONE 'America/Chicago'`, it is well defined for every row in this corpus, and
local-time-first is not merely preferable here — it is the only correct order of operations. This
is locked decision 2.

**Timezone determination, in preference order for this vendor:** declared by the publisher in
package metadata (`schema.json`, `README.md`) → declared at upload → inferred from the
maintenance-break histogram. The declared value and the inferred value agree.

### 4.2 Daily timestamps carry no time of day

`epoch_ms(timestamp_ms)::DATE = date` on all 30,102 rows, no non-midnight times, no negative
values. A daily row is a date; the session it summarises must be inferred (§5.1).

### 4.3 Bar stamping: interval start

Three independent lines of evidence, all agreeing:

| Evidence | Observation | Implication |
|---|---|---|
| Weekly boundary | Last Friday bar is `15:59`; first Sunday bar is `17:00` | Session closes 16:00, so 15:59 is the last *start* |
| Daily dead zone | `[16:00, 16:59]` absent, and 15:59 present | A 16:00 slot would exist if stamps were interval-end |
| Expiry day | All five ES contracts' final bar is `08:29` on expiry | ES terminates 08:30 CT; 08:29 is the last full minute *begun* |

`ts_convention` is recorded on the batch as `interval_start`.

### 4.4 Bar interval: one minute, and how to infer it

Modal consecutive delta is 60 s for all eight roots, minimum delta is 60 s (no sub-minute rows),
and **not one of the 5,295,199 consecutive deltas fails to be an exact multiple of 60 seconds.**

**The modal-share metric is not a usable gate.** Modal share reads 67.8%–91.0% across the eight
roots, because illiquid minutes are simply absent, so a 0.8 threshold would reject the correct
one-minute inference for six of eight roots. **The acceptance test is: the modal delta equals a
recognised interval *and* every delta is an exact integer multiple of it.** That holds at 100% for
all eight roots and is not degraded by sparsity. Modal share stays as a reported diagnostic
(`interval_confidence`), never as a gate.

---

## 5. Sessions

Derived by run-length encoding the `minute_of_day` values that never appear per root. All windows
are `America/Chicago`, interval-start, because the vendor expressed every venue in Chicago time.

| Root | Exch | Observed session (local) | Slots/session | Dead zones (local) |
|---|---|---|---|---|
| CL | NYMEX | 17:00 → 15:59 next day | 1,380 | 16:00–16:59 |
| ES | CME | 17:00 → 15:59 next day | 1,380 | 16:00–16:59 |
| GC | COMEX | 17:00 → 15:59 next day | 1,380 | 16:00–16:59 |
| SR3 | CME | 17:00 → 15:59 next day | 1,380 | 16:00–16:59 |
| ZN | CBOT | 17:00 → 15:59 next day | 1,380 | 16:00–16:59 |
| VX | CFE | 17:00 → 16:00 next day | 1,381 | 16:01–16:59 |
| SB | ICEUS | 02:30 → 11:59 same day | 570 | 12:00–02:29 |
| ZC | CBOT | 19:00 → 07:44, then 08:30 → 13:19 | 1,055 | 07:45–08:29 and 13:20–18:59 |

**Three distinct session shapes, not eight.** CL, ES, GC, SR3 and ZN are identical in session
shape. **A full CME-family minute session is 1,380 slots** (420 from 17:00–23:59 plus 960 from
00:00–15:59) — not 1,365; there is no 15:15–15:30 halt in this data, where minutes 15:15–15:29
each carry 391–436 ES bars.

**The 1,380 coincidence, which defeats the obvious sanity check.** A full calendar day is also
1,380 minutes (1,440 − 60). A naive `GROUP BY date(timestamp)` therefore gets the expected *count*
exactly right while getting the *membership* wrong for the 420 evening slots. Completeness will
look perfectly healthy while every bar is wrong. This warrants a comment in the code.

**VX is the CME profile, not a third case.** The 16:00 slot exists on three bars in 373,886 — all
flat, negligible volume, two isolated dates. Seed VX on the CME 1,380 profile and let those three
rows raise `CON.RECORD_IN_HALT` at `warning`.

**SB is a vendor normalisation artefact worth documenting.** A single 570-minute window fixed at
02:30–11:59 in all twelve calendar months: ICE Sugar No. 11 trading 08:30–18:00 London,
re-expressed in Chicago time with London's DST calendar *not* tracked. For the three weeks a year
when UK and US clocks are out of step, the true London window maps to a different Chicago window
than the file shows. Present it as the vendor's normalisation, not as the exchange's session.

**ZC needs two windows.** 19:00–07:44 and 08:30–13:19, stable at 1,055 distinct minutes in all
twelve months. This is what makes `ref.product.halt_windows` a list rather than a window.

### 5.1 Seeding `ref.product` / `ref.session_calendar`

Seed **eight rows over three profiles**, all derived from the data itself, none requiring an
external calendar source:

| Profile | Roots | Slots |
|---|---|---|
| CME 23-hour | CL, ES, GC, SR3, ZN, and VX | 1,380 |
| ICE single-window | SB | 570 |
| CBOT grain two-window | ZC | 1,055 |

Ship the dead-zone run-length query as the **data-inferred fallback** for any root that is not
seeded. It reproduced all three profiles correctly with no reference data, and it is what makes a
new exchange a configuration change rather than a code change.

### 5.2 Holidays

Holidays cannot be inferred as cleanly. Full closures are correctly absent — no daily rows on
12-25 or 01-01 for any contract — but partial holidays are present as rows, sometimes with zero
volume and sometimes not (2021-11-11: 9 contracts, 0 volume; 2024-12-24: 27 contracts, 863,051
volume). A hardcoded holiday list for **2021 through 2026** is the right call, validated against
the observed daily dates rather than trusted.

**Only full closures set `is_holiday`, and in this corpus there are exactly two of them: New
Year's Day and Christmas Day.** They are the only dates with no daily row for any contract in any
year from 2017 to 2026, and they carry `expected_slots_1m = 0`.

Validating the list against the data rather than trusting it is what establishes that, and it
contradicts the intuitive answer. Every other US market holiday carries rows, and usually volume,
because CME Globex runs a shortened session:

| Date | Holiday | Contracts with a row | Volume |
|---|---|---|---|
| 2023-04-07 | Good Friday | 5 | 21,390 |
| 2025-05-26 | Memorial Day | 3 | 277 |
| 2025-07-04 | Independence Day | 3 | 1,173 |
| 2025-11-27 | Thanksgiving | 4 | 9,171 |
| 2024-12-24 | Christmas Eve | 27 | 863,051 |

So Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, MLK Day,
Presidents Day, 3 July, the day after Thanksgiving and Christmas Eve all set `is_early_close`
instead, and carry a **null** `expected_slots_1m`: the session exists and we do not know its
truncated grid, and a null is the honest way to say the completeness denominator is unknown rather
than zero. Marking them as holidays would tell the completeness rule that no session was expected
on a day that plainly has one.

**There is no US-observance shifting.** Federal observance moves New Year's Day back to Friday
31 December when 1 January falls on a Saturday; the exchange does not, and 2021-12-31 carries 506
lots across 11 contracts here. A Sunday closure does move to the Monday — 2022-12-26 has no rows —
and a Saturday one simply never becomes a trade date.

---

## 6. The oracle

**The vendor `daily` files are a genuine ground-truth oracle for the `open`, `high` and `low` of
our minute-to-daily aggregation, agreeing on 96.48% of complete sessions across eight roots and
six exchanges. They are not an oracle for `close` or `volume`.**

This is a *consistency* oracle between two of the same vendor's products, not an independent
source of truth. The claim is **"agrees with the vendor's daily bars"**, never "verified correct".
It tests a definition chosen independently and is never used to derive one.

### 6.1 The recovered session boundary

Aggregate minute rows to daily under a candidate boundary, inner-join to the vendor daily row on
`(contract_symbol, date)`, compare field by field. Vary only the boundary:

| Candidate | ES `open` match | Range across all eight roots |
|---|---|---|
| Vendor `trading_date` column (= Chicago calendar date) | 17.1% | 17.1%–100% |
| Session roll at 17:00 CT | 97.7% | 97.8%–100% |

**The vendor's daily files are built on the CME 17:00 CT session roll.** SB is unchanged between
candidates because its 02:30–11:59 session never crosses 17:00, which is a useful control. A
boundary at 16:00 gives identical results because no bar exists in 16:00–16:59; 17:00 is correct
on domain grounds.

Two independent confirmations select the same boundary: weekend-dated minute rows are 179,934
(3.40%, all Sundays) under the vendor `trading_date` column and **0 for all eight roots** under the
recovered roll; and the vendor's daily `date` column has zero Saturdays and zero Sundays across all
30,102 rows.

**The vendor package is internally inconsistent, and this is the most instructive thing in the
corpus.** `trading_date` in the minute files is a Chicago calendar date; `date` in the daily files
is a session date on the 17:00 roll. They disagree for every evening bar. **`trading_date` is a
convenience column that Loupe does not use**, and the disagreement is surfaced in the UI as a
documented vendor quirk rather than silently resolved.

### 6.2 Agreement, on complete sessions

Coverage is the confounder: an incomplete minute session cannot reproduce the daily high and low.
Restricting to sessions holding at least 98% of the per-root maximum slot count — 654 sessions
across all eight roots:

| Field | Exact agreement |
|---|---|
| `open` | 98.32% |
| `high` | 99.08% |
| `low` | 97.86% |
| all three | **96.48%** |

ES alone, on the 208 sessions holding exactly 1,380 bars:

| Field | Agreement | Direction of disagreement |
|---|---|---|
| `open` | 202 / 208 (97.1%) | — |
| `high` | 205 / 208 (98.6%) | daily higher in 3, lower in **0** |
| `low` | 206 / 208 (99.0%) | daily lower in 2, higher in **0** |
| `close` | 1 / 208 (0.5%) | median difference 4.25 index points |
| `volume` | 0 / 208 | median ratio 0.9509 |

**The vendor daily range is never narrower than the minute-derived range, only ever wider**, on
every root. The daily file contains block trades and privately negotiated transactions reported to
the exchange but never appearing as continuous-market minute bars. The residual disagreement is a
property of the feed, not an error in the aggregation.

### 6.3 Why `close` does not match — it is a settlement

Median absolute error against the vendor daily close over the 208 complete ES sessions: 1.00 point
for the close of the 14:59 bar (as at 15:00 CT), 3.00 for the 15:14 bar, 4.25 for the 15:59 bar
(last trade of session), 4.25 for the last bar overall. Closest to the 15:00 mark, exactly equal to
none — the signature of an exchange **settlement price**.

The decisive corroboration is off-tick prices. ES trades in 0.25 increments and 3,500 of 3,505 ES
daily rows are on that lattice. The five that are not are one per contract, each on that
contract's expiry date (`ESZ25` 2025-12-19 at 6796.54, and four siblings) — final settlements
derived from the S&P 500 Special Opening Quotation, which is computed from index constituent
opening prices and is under no obligation to land on a futures tick. **A price column containing
five values that cannot have traded is not a trade price.**

The framing that follows: a settlement feed is not "a separate source we lack" — it is the `close`
column of the daily config. We choose last-trade for our own bars *and can show the difference*.

### 6.4 Why `volume` does not match

ES minute-sum ÷ vendor daily: p05 0.6068, p25 0.9345, **p50 0.9509**, p75 0.9589, p95 0.9683. The
tape carries about 95% of reported daily volume and the daily figure is larger in 207 of 208
complete ES sessions — the same block activity that widens the daily high and low. The low tail
falls on roll dates, where much volume trades as calendar spreads. VX is the exception: volume
agrees exactly on 75.7% of matched days.

### 6.5 How the oracle is used in tests

- Assert `open`, `high`, `low` agreement **above 95%** (measured 96.48%) over complete sessions,
  per root.
- Assert that where high and low disagree, **the vendor value is the wider one**. This is a
  stronger invariant than the percentage, and it held on all 654 complete sessions — but **only on
  complete ones**. Across all 2,400 matched sessions regardless of coverage it breaks 31 times,
  always on sparse sessions (mean 406 bars against 1,380) and always by a tick or less. **Gate the
  assertion on minimum coverage.** `specs/dq-rules-and-scoring.md` carries the coverage-gated form
  as `REC.OHLC_DISAGREE`.
- **Do not assert on `close` or `volume`.** Assert the *explanations* instead: the vendor close
  sits nearer the 15:00 mark than the session end, and the vendor volume is ≥ the minute sum.
- Keep the boundary-recovery experiment itself as a test. If `open` agreement under a calendar-date
  boundary ever stops being dramatically worse than under the session boundary, something has
  changed.
- The oracle test is **marked optional and skipped when `data/samples/` is absent.**

---

## 7. Measured quality baselines

Every rule family was run over the full corpus, not a sample. These are the calibration figures
the rule catalogue is tuned against.

### 7.1 Minute config — 5,295,239 rows: effectively defect-free

Zero occurrences of: null price, null volume, non-positive price, negative volume, off-tick price
(all eight roots), zero-volume-with-range, `high < low`, open/close out of range, exact duplicate,
key conflict, out-of-order timestamp, off-grid timestamp. `CON.WEEKEND_RECORD` on the **recovered**
session date: zero. On the vendor `trading_date` column: 179,934 — all false positives.

Two entries need interpretation rather than a count:

**Flat bars are not defects.** 48.34% of minute bars have `high = low`, every one with non-zero
volume. The rate tracks liquidity: ES 11.0%, GC 25.3%, CL 31.8%, ZN 34.7%, VX 41.9%, SB 52.4%,
ZC 57.6%, SR3 79.6%.

**`CON.STALE_REPEAT` at the default `n = 10` fires 14,830 times and is mostly wrong.** SR3
contributes 13,285 of them — a rate contract in a three-point band, where an unchanged price for 94
consecutive minutes is ordinary. ES and GC produce **zero**, which is the correct answer for liquid
instruments and shows the rule is sound. The threshold must be per-root or liquidity-scaled, with a
global default nearer 30.

### 7.2 Tick sizes, measured

Largest increment on which 100% of minute prices lie:

| Root | Tick | Note |
|---|---|---|
| CL | 0.01 | |
| ES | 0.25 | Exact in IEEE 754 |
| GC | 0.10 | |
| SB | 0.01 | Cents per pound |
| SR3 | 0.0025 | **Rate contract**: price = 100 − rate; band 95.55–98.69 |
| VX | 0.01 | Daily `close` is finer — see below |
| ZC | 0.25 | **Quoted in cents per bushel**; 475 means $4.75 |
| ZN | 0.015625 (1/64) | 64 distinct residues observed; 0 off-tick in 488,029 rows |

**The floating-point warning points at the wrong ticks in the primer.** 1/64 and 0.25 are dyadic
rationals and are exact in IEEE 754. The ticks that are genuinely inexact are **0.01, 0.10 and
0.0025**. The epsilon comparison is right; the example was backwards.

`VAL.PRICE_MAGNITUDE` bands must be per root: a band suiting ES at ~6,000 or ZC at ~500 passes
anything for SR3 at ~97.

### 7.3 The tick lattice differs by config for the same root

| Root, config | Off-tick rows |
|---|---|
| VX, minute | 0 of 373,886 |
| VX, daily | **805 of 959 (83.9%)** |
| ES, minute | 0 of 595,430 |
| ES, daily | 5 of 3,505 |

VX daily `open`, `high` and `low` are all on 0.01; only `close` is not, because it is the
settlement carried to four decimals (e.g. `VXH26` 2026-03-16 close 23.3145). **This is why the tick
lookup is keyed `(root, frequency, field)`** (`specs/data-model.md` §2, `ref.tick`), and it is the
live worked example for the suggestion engine: the correct suggestion is to fix the `tick_size`
reference, not to exclude 83.9% of a contract's prices.

### 7.4 Completeness — the daily config is complete, the minute config is legitimately sparse

Daily coverage against every weekday in each contract's own span: 96.0%–99.0% per root. The
consistent ~4% shortfall is US market holidays. Nothing is missing that should be there.

Minute sessions with any data, as a percentage of weekdays in span: CL 45.8%, ES 60.2%, GC 65.5%,
ZC 80.2%, SR3 90.0%, SB 91.0%, ZN 94.3%, VX 98.0%. For `ESZ25`, 502 weekdays fall inside its minute
span and **278 have no minute data at all.**

The volume profile makes the cause unmistakable. ES minute volume by days-to-expiry bucket: 866
contracts at 270 days, 51,459 at 180, 406,696 at 120, 91,851,494 at 90, 154,695,062 at 60. **Volume
rises by six orders of magnitude between 120 and 90 days to expiry.** Before that the contract is
listed but not traded.

**Consequence, and it is binding on the rule catalogue.** The `[first_trade_date,
last_trade_date]` bounds and the `ROL.*` suppressions are **load-bearing, not optional**. Without
them `CMP.SESSION_MISSING` alone emits 278 `error` findings for one contract describing normal
deferred-contract behaviour, and completeness would report the corpus as ~45% complete for CL when
nothing is missing. Drive completeness from a per-contract **liquidity** window — first and last
session above a volume floor — rather than the full listed span.

### 7.5 The defects are natural, not planted

Zero nulls, duplicates, key conflicts, non-positive prices, negative volumes, `high < low`,
out-of-order rows and off-tick prices across 5.3 million minute rows. Every defect that does exist
has a market-structure explanation: settlement outside the traded range on untraded deferred
contracts, the S&P Special Opening Quotation not landing on a futures tick, VIX settlements carried
to four decimals, illiquid contracts with flat prices. The publisher documents the two odd
behaviours in advance and quantifies them per file. Independent recomputation reproduced the
vendor's own diagnostics on all 80 files.

**Consequence for the demo.** The corpus will not demonstrate the quality features on its own. Lead
with the real findings that do exist — the 43 invalid-OHLC daily rows, the VX off-tick settlements,
the `trading_date` inconsistency — plus **labelled** defect injection with a ground-truth manifest.
Never silently corrupt pristine samples. See `plans/06-rec-suggestions-demo.md`.

---

## 8. The committed local subset

The full corpus is 105.62 MB. `tools/fetch_samples.py` fetches a curated 15.5 MB subset into the
gitignored `data/samples/`, preserving the vendor layout: **all 40 daily files** (1.02 MB — the
best-value decision available, giving every contract, the complete oracle, all 43 invalid-OHLC
rows, all 811 off-tick rows), **eight minute files, one per root**, and the seven vendor metadata
files.

| Minute file | Rows | Why this one |
|---|---|---|
| `CME/ES/ESZ25.parquet` | 114,477 | The oracle pair; expires 2025-12-19 inside the window |
| `CFE/VX/VXZ25.parquet` | 73,978 | CFE; the off-tick settlement case |
| `ICEUS/SB/SBK26.parquet` | 123,591 | ICE; the 02:30–11:59 short session |
| `CBOT/ZC/ZCH26.parquet` | 139,406 | CBOT grains; the **two-window** session |
| `CBOT/ZN/ZNZ25.parquet` | 94,021 | The 1/64 tick lattice |
| `NYMEX/CL/CLG26.parquet` | 105,384 | NYMEX; sparsest minute coverage (45.8%) |
| `COMEX/GC/GCH26.parquet` | 30,180 | COMEX; smallest useful minute file |
| `CME/SR3/SR3G26.parquet` | 345 | Rate contract; deliberately tiny, for fast tests |

Between them these cover all six exchanges, all eight roots, both frequencies for the same
contract, all three session profiles, both odd tick regimes, a contract expiring inside the window,
and file sizes from 345 to 139,406 rows.

### 8.1 What the curated subset actually fires — measured

The selection above was curated for **ingest** diversity, and the question it never answered is
which of the 37 engine rules a reviewer would see fire. Measured over the whole subset — 48 files,
711,484 records, one corpus-wide run — **17 do**:

| Fires naturally | Findings |
|---|---|
| `CMP.MISSING_TIMESTAMP` | 135,808 |
| `OUT.RETURN_MAD` | 19,666 |
| `CMP.PARTIAL_SESSION` | 1,190 |
| `REC.VOLUME_SHORTFALL` | 1,088 |
| `VAL.ZERO_VOLUME_WITH_RANGE` | 400 |
| `CMP.SESSION_MISSING` | 382 |
| `REC.CLOSE_CONVENTION` | 325 |
| `OUT.VOLUME_MAD` | 186 |
| `VAL.OFF_TICK_PRICE` | 62 |
| `CON.CLOSE_OUT_OF_RANGE` | 42 |
| `REC.OHLC_DISAGREE` | 25 |
| `REC.SESSION_ONLY_IN_ONE` | 13 |
| `VAL.EXTREME_VOLUME`, `CON.PRICE_JUMP` | 10 each |
| `ROL.NO_SUCCESSOR` | 9 |
| `ROL.THIN_NEAR_EXPIRY` | 5 |
| `CON.OPEN_OUT_OF_RANGE` | 2 |

**Twenty do not, and that is a fact about the data rather than a shortfall in the selection.**
§7.1 measures the minute config as effectively defect-free and §7.5 records that the defects that
do exist are natural, not planted. No file in this package will demonstrate `UNQ.KEY_CONFLICT`,
`CON.HIGH_LT_LOW` or `VAL.NEGATIVE_VOLUME`, because nothing is wrong with them. Widening the
selection cannot fix that; **labelled injection is the answer** (`specs/loupe-solution-design.md`
§9), and `loupe.demo.injection` plants nine defect types of which six are otherwise unreachable:
`VAL.NEGATIVE_VOLUME`, `CON.HIGH_LT_LOW`, `CMP.NULL_FIELD`, `VAL.PRICE_MAGNITUDE`,
`UNQ.EXACT_DUPLICATE` and `UNQ.KEY_CONFLICT`. That takes the demonstrable set to 23 of 37.

Three absences are worth reading rather than skipping:

- **The whole `TIM.*` family is silent.** Timestamps in this package are monotonic, on-grid, and
  inside the listed span; `TIM.TIMEZONE_MISALIGNED` needs a deliberately corrupted derivative
  (§15) because the vendor's own timezone handling is consistent, even where it is confusing.
- **`CON.STALE_REPEAT` does not fire**, though §7.1 measured 14,830 flat-price runs at `n = 10`.
  The seeded default is `n = 30` with per-root overrides up to 120, calibrated so an illiquid rate
  contract is not reported for behaving like one. The rule and the calibration disagreeing with a
  raw count is the calibration working.
- **`CON.DERIVED_BAR_INVALID` refused** in this measurement, because it reads `mart.bar_daily` and
  bars had not been built. Ingest builds them after every load, so it is evaluated in the app;
  the refusal here is an artefact of measuring with `load_file` directly.

**Cost, for anyone waiting on it.** Loading the 48 files takes about 33 seconds and the
corpus-wide validation about 11 — so the demo button is roughly three quarters of a minute, and
**parsing the files is now the slow half**. Of the 159,223 findings, 136,000 are missing minute
slots: legitimate sparsity in the deferred contracts (§7.4), not a defect.

The run was four minutes when first measured, and none of that was analysis. 160 seconds went on
inserting 145,236 metric rows one statement at a time against a composite key, and 37 on writing
the findings the same way; the queries behind both take a tenth of a second. `specs/data-model.md`
§5 carries the rule that came out of it, and `specs/api-contract.md` §4.4 carries the latency
budget that should have caught it earlier.

**Two of the eight minute files load as CSV**, converted from their Parquet by
`loupe.demo.corpus`: the earliest by `first_timestamp_ms` and the smallest by `row_count`. The
vendor ships only Parquet, so without this the CSV half of "accept CSV or Parquet" would never
run outside the test suite. A converted file **replaces** its Parquet in the load rather than
joining it — two copies of one tape differ only in format, and loading both would make almost
every row an exact duplicate.

**Test fixtures are a separate concern with a different answer.** The real files are unsuitable as
unit-test fixtures: too large, not committable, and far too clean to exercise the rule catalogue.
Fixtures are tiny, hand-built, committed CSVs under `tests/fixtures/`, each carrying exactly one
planted defect so a failing test names the rule it broke. `specs/dq-rules-and-scoring.md` owns the
fixture-to-rule mapping.

---

## 9. Verified versus assumed

**Verified by execution** against all 93 files: both Parquet schemas including physical types and
nullability; null counts in every column; presence and path-consistency of `contract_symbol`;
equality of `timestamp_ms` and `timestamp_chicago_wall`; hour- and minute-of-day histograms; the
16:00–16:59 dead zone; the smeared-dip signature of the wrong timezone assumption; DST offsets by
month and the absence of non-existent local times; interval-start stamping from three independent
boundaries; the one-minute interval and the multiple-of-60 property of all 5,295,199 deltas;
per-root session windows and dead zones; the minute-to-daily comparison under two boundary
candidates; per-field oracle agreement; the settlement evidence; measured tick sizes; every rule
baseline in §7.

**Assumed or external:** the holiday list (validated against observed dates, not derived);
`roll_date`, which is absent from the package; exact expiry specifications, which the publisher
states are not in the source.

**Reproducing this.** Full download is 105.62 MB across 93 files, about 28 seconds. DuckDB reads
the corpus directly with `read_parquet('data/minute/*/*/*.parquet')`; the heaviest query above (the
all-roots oracle join over 5.3 million rows) runs in about two seconds, so no materialisation or
indexing is needed. The `icu` extension is required for every `AT TIME ZONE` expression.
