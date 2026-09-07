# Loupe — Analytics semantics

**Normative.** Trade-date assignment, the expected-timestamp grid, daily OHLCV aggregation,
rolling 15-minute VWAP, and the MAD method for `OUT.*`. Promoted from research
`_notes/cursor/02-analytics-semantics.md` (now archaeology). Summary: `specs/loupe-solution-design.md`
§8. Storage: `specs/data-model.md`. Sample and oracle claims cited here are owned by
`specs/sample-corpus.md`. Rule IDs and severities: `specs/dq-rules-and-scoring.md`.

Revised 2026-09-08: the reviewer passes one explicit frequency/source to checks and bars.
Revised 2026-09-07: the reviewer overlay is not the `max_severity` join (§3.3).
Revised 2026-09-05: promoted from research; first normative version. Same day: §3.1 defines
`open_interest` on a derived bar (last reported, never summed) — `mart.bar_daily` carried the
column with no definition behind it. Same day: §3.3 defines which findings intersect a
bar, by `dq.dq_rule.scope`. Slice 3, on implementing both: §3.2 records that the compact
`arg_min` / `arg_max` form is not a drop-in for the reference form unless the value is
struct-wrapped, and §3.3's `file` row joins on the finding's timestamp span, because
`dq.dq_finding` has no `batch_id` to join on.

Validated against DuckDB 1.4.5 with the `icu` extension. Every SQL snippet below was executed
before being written down. These calculations belong in the `insights` layer (bars, VWAP) and
the `quality` layer (the expected grid). No SQL from this document appears in a Streamlit
callback.

**Scope of authority.** This spec owns *how a trade date is assigned, how the expected grid is
built, how a daily bar is aggregated, how rolling VWAP is windowed, and the MAD formula*. It
does not own DDL, rule IDs, or measured sample percentages. A number that appears here is a
citation of `specs/sample-corpus.md` unless it is a definition (1,380 slots from 17:00
inclusive to 16:00 exclusive, the VWAP `RANGE` frame, the MAD constants).

**Build sequence.** Timestamp policy and the session calendar are already shipped (slice 1).
Completeness consumes the grid (slice 2). Daily bars, VWAP, `CON.DERIVED_BAR_INVALID` and
`OUT.*` are slice 3.

---

## 0. Timestamp normalisation — the prerequisite

Everything below depends on this being done once, correctly, at ingest. Storage and batch
columns are owned by `specs/data-model.md`; this section is the policy those columns record.

**Policy**

- Store `ts_utc` as `TIMESTAMPTZ`. This is the sort key and the join key.
- Store `ts_exchange` as a naive `TIMESTAMP` holding the exchange wall clock. Session logic
  operates on this; the UI displays it.
- Reject any timestamp that cannot be parsed. Do not guess.

**If the source timestamps are naive** (no offset — the common case, and the case for the
development sample), decide what they mean. Ranked by preference:

1. **Declared by the publisher in package metadata.** Strongest evidence; costs nothing to read.
   The development sample declares `America/Chicago` in `schema.json` and `README.md`, and the
   inference in step 3 independently agrees (`specs/sample-corpus.md` §4.1).
2. **A declared timezone supplied at upload** — explicit and auditable, but it is the
   uploader's assertion rather than the publisher's.
3. **Inferred from the data:** histogram of activity by hour; look for the 60-minute dead zone.
   A CME-hours file has an unmistakable one-hour hole. If that hole sits at 16:00–17:00, the
   file is exchange-local Chicago; if it sits at 22:00–23:00, the file is UTC. This is also the
   detector for `TIM.TIMEZONE_MISALIGNED` (`specs/dq-rules-and-scoring.md` §7).
4. **Default to UTC** and say so in the UI.

Record *which* rung supplied the answer, on the batch. "Declared in package metadata, confirmed
by the maintenance-break histogram" and "defaulted to UTC because nothing else was available"
carry different weight.

**The epoch-milliseconds trap.** An integer column named `timestamp_ms` looks like an instant
and need not be one. On this vendor it is a local wall-clock reading encoded through a UTC
epoch function: reading it as epoch-milliseconds reproduces the Chicago wall-clock column on
every row (`specs/sample-corpus.md` §4.1). Applying a UTC-to-local conversion therefore shifts
every record by five or six hours, and nothing downstream complains. Never infer that a column
is an instant from its name, its type, or the fact that an epoch function accepts it. Establish
the zone by the ladder above, then attach it.

**Why local-time-first matters.** Build the session grid in exchange-local wall clock and then
convert to UTC. Sessions are constant in local time (always 17:00–16:00 for the CME profile)
but their UTC span shifts by an hour twice a year at DST. Arithmetic in UTC introduces a
one-hour error in March and November; arithmetic in local time makes DST a non-event. Where the
source *is* local time — this sample's files contain no UTC instant at all — local-time-first
is the only correct order of operations. `ts_utc` is then a derived column, and the derivation
is an ingestion decision on the batch (locked decision 2).

```sql
-- verified, DuckDB 1.4.5 with icu, session TimeZone = 'UTC'
SELECT (TIMESTAMPTZ '2025-09-14 22:30:00+00') AT TIME ZONE 'America/Chicago';
-- 2025-09-14 17:30:00               (TIMESTAMPTZ -> naive local)

SELECT (TIMESTAMP '2025-09-14 17:30:00') AT TIME ZONE 'America/Chicago';
-- 2025-09-14 22:30:00+00            (naive local -> TIMESTAMPTZ, CDT, -5)

SELECT (TIMESTAMP '2025-12-14 17:00:00') AT TIME ZONE 'America/Chicago';
-- 2025-12-14 23:00:00+00            (same local time in CST, -6)
```

The two `17:00` local values land an hour apart in UTC.

`AT TIME ZONE` is direction-sensitive by input type: applied to a `TIMESTAMPTZ` it strips to
local wall clock; applied to a naive `TIMESTAMP` it attaches a zone. Requires `icu`. A
`TIMESTAMPTZ` renders in the session's `TimeZone` setting, so set it explicitly in tests.

### 0.1 The negative signature

The intuitive failure model is wrong. If naive labels are read as UTC and converted to
exchange-local, the dead zone **does not move**. It splits into two adjacent partial dips,
neither empty, because standard-time and daylight-time offsets differ: the break lands in one
local hour for part of the year and the neighbouring hour for the rest, and each hour is
partly backfilled by genuine activity from the other half of the year.

Measured signature: `specs/sample-corpus.md` §4.1. Face-value Chicago: hour 16 holds exactly
zero bars. Wrong UTC reading converted to Chicago: no empty hour; two partial dips one hour
apart.

**`TIM.TIMEZONE_MISALIGNED` tests both signatures.** A smeared pair of partial dips is the
fingerprint of a double conversion; a displaced *empty* hole is a fixed-offset error. They
have different causes and different fixes. Require the genuine hole to be *empty*, not merely
thin — a threshold-based "unusually quiet" test fires on both the true and the false reading.

---

## 1. Trade date assignment

**Definition.** The trade date of a record is the date on which its session *closes*.

Do not hardcode 17:00. The roll uses `ref.product.session_open_local` (and
`spans_midnight`) from the seeded profile, persisted per date on `ref.session_calendar`
(`specs/data-model.md` §2). CME-family defaults are a seeded ruleset, not the definition.

For a session that spans midnight, with open at `session_open_local`:

```
trade_date = local_date(ts_exchange)           if local_time(ts_exchange) <  session_open_local
           = local_date(ts_exchange) + 1 day   if local_time(ts_exchange) >= session_open_local
```

A session that stays inside one calendar day never rolls (SB: 02:30–12:00).

```sql
-- verified equivalent of src/loupe/data/sessions.py:trade_date_for
CASE WHEN p.spans_midnight AND ts_exchange::TIME >= p.session_open_local
     THEN (ts_exchange::DATE + INTERVAL 1 DAY)::DATE
     ELSE  ts_exchange::DATE
END AS trade_date
```

Worked example: the exchange-local label `2025-09-14 17:30:00` is 17:30 CT on **Sunday** 14
September and yields trade date **Monday 2025-09-15**. Grouping `ESZ25` over that boundary puts
one contiguous session on 2025-09-15, running from `2025-09-14 17:00` to `2025-09-15 15:59`.
That is the case a naive `GROUP BY date(timestamp)` gets wrong, and §2.2.2 explains why the
error is invisible to a count-only check.

The boundary is recoverable from the data. Vendor daily files are built on the CME 17:00 CT
session roll; a calendar-date grouping collapses open-price agreement. Keep that comparison as
a live test (`specs/sample-corpus.md` §6.1). Vendor minute `trading_date` is a Chicago calendar
date and is **not** used.

After assignment, no valid CME-family record carries a Saturday or Sunday trade date: Friday's
close ends the week and Sunday evening already rolls into Monday. That check is
`CON.WEEKEND_RECORD`, computed on the *derived* session date only
(`specs/dq-rules-and-scoring.md` §6). A record whose `ts_exchange` falls outside
`[session_open, session_close)` or inside an intra-session halt is `CON.RECORD_IN_HALT` — for
CME-family that includes the 16:00–17:00 maintenance gap, which is *between* sessions and is
not listed in `halt_windows` (§2.2).

Vendor daily rows: the source `date` is already a session date on the 17:00 roll
(`specs/sample-corpus.md` §6.1). Ingest takes it as `trade_date` directly.

---

## 2. The expected-timestamp grid

Gap detection has no meaning without a denominator.

### 2.1 Infer the bar interval

Take the modal difference between consecutive timestamps as the candidate interval, then test
that candidate by **divisibility**, not by how often it occurs.

Modal share of consecutive deltas measures liquidity, not sampling rate. A one-minute series
in which illiquid minutes are absent has consecutive rows two, three or ten minutes apart, so
the modal share falls well below 1 while the interval is still exactly one minute. A 0.8
threshold would reject the correct one-minute inference for six of eight roots on this corpus,
and would reject them hardest for the sparsest series — the ones whose completeness we most
want to measure. Rates: `specs/sample-corpus.md` §4.4.

The gate is that every observed delta is an exact integer multiple of the candidate. A missing
minute produces a delta of two minutes, which still divides. A series that is not on a
one-minute grid produces a delta that does not.

```sql
-- verified against data/minute/*/*/*.parquet, DuckDB 1.4.5
-- Two stages, deliberately: mode() cannot be nested inside another aggregate's FILTER.
WITH deltas AS (
  SELECT
    contract_id,
    ts_utc - lag(ts_utc) OVER (PARTITION BY contract_id ORDER BY ts_utc) AS d
  FROM stage.market_record
  WHERE frequency = 'minute'
),
candidate AS (
  SELECT contract_id, mode(d) AS inferred_interval
  FROM deltas WHERE d IS NOT NULL
  GROUP BY contract_id
)
SELECT
  c.contract_id,
  c.inferred_interval,
  count(*) FILTER (WHERE epoch(d.d)::BIGINT % epoch(c.inferred_interval)::BIGINT <> 0) = 0
    AS grid_aligned,
  count(*) FILTER (WHERE d.d = c.inferred_interval) * 1.0 / count(*) AS modal_share,
  min(d.d) AS min_delta,
  count(*)  AS deltas
FROM candidate c
JOIN deltas d USING (contract_id)
WHERE d.d IS NOT NULL
GROUP BY 1, 2;
```

Accept the inference when the modal delta snaps to a recognised interval (1s, 1m, 5m, 15m, 1h)
**and** `grid_aligned` is true. Keep `modal_share` and `min_delta` as diagnostics on the batch
(`interval_confidence`); a low modal share is a statement about sparsity, not evidence against
the interval. The recognised set and the divisibility requirement are configuration.

If the divisibility test fails, fall back to a frequency declared at upload; if there is none,
skip completeness checks for that series and say why. A failed test means the file mixes
sampling rates — a finding, not a nuisance.

Record the inferred interval, the divisibility verdict and the modal share on the batch. Never
re-infer them inside a query.

### 2.2 Generate the grid

For each `(contract, trade_date)`, expand the session in local time at the inferred interval,
subtract **intra-session** halt windows, then convert to UTC.

**`halt_windows` holds intra-session halts only** (`specs/data-model.md` §2.1). A session of N
contiguous blocks carries N−1 of them. The gap between one session's close and the next one's
open is already expressed by `session_open_local` / `session_close_local` and must not be
repeated, or the grid is short by the overnight break.

- CME-family: open 17:00, close 16:00 *exclusive* (last slot 15:59, interval-start). The
  16:00–17:00 maintenance break falls *between* sessions. `halt_windows` is empty. 23 h − 0 =
  **1,380**.
- ICE (SB): open 02:30, close 12:00 exclusive (last slot 11:59). No halt. 9 h 30 − 0 = **570**.
- CBOT grain (ZC): open 19:00, close 13:20 exclusive (last slot 13:19), one halt 07:45–08:30
  exclusive (slots 07:45–08:29). 18 h 20 − 45 = **1,055**. The 13:20–19:00 gap is between
  sessions, not a second halt.

Invariant, asserted by the seeding tests: **`expected_slots_1m` equals the session span in
minutes minus the halted minutes.**

```sql
-- verified: 1,380. generate_series is inclusive; close is exclusive, so end at 15:59.
SELECT count(*) FROM generate_series(
  TIMESTAMP '2025-09-24 17:00:00',
  TIMESTAMP '2025-09-25 16:00:00' - INTERVAL 1 MINUTE,
  INTERVAL 1 MINUTE);
-- 1380
```

In production, generate the span once and subtract halt windows rather than assembling
hand-split pieces:

```sql
-- same 1,380 for CME (the halt predicate is a no-op: 16:00–16:59 is already outside the span)
SELECT count(*) FROM (
  SELECT unnest(generate_series(
           TIMESTAMP '2025-09-24 17:00:00',
           TIMESTAMP '2025-09-25 16:00:00' - INTERVAL 1 MINUTE,
           INTERVAL 1 MINUTE)) AS ts
) WHERE NOT EXISTS (
  -- halt_windows: list of [start, end) local times; empty for CME
  SELECT 1 FROM (SELECT TIME '07:45:00' AS h_start, TIME '08:30:00' AS h_end) h
  WHERE ts::TIME >= h.h_start AND ts::TIME < h.h_end
);
```

A product with two intra-session halts needs no new code; ZC has one. There is **no
15:15–15:30 halt** in this data (`specs/sample-corpus.md` §5). Subtracting that window would
understate the denominator by fifteen slots on every CME session and manufacture a phantom gap.

Slot counts and the three profiles (CME 23-hour, ICE single-window, CBOT grain two-window) are
owned by `specs/sample-corpus.md` §5. Seed them as `ref.product` defaults. **VX is the CME
1,380 profile**, not a 1,381 special case: three bars in 373,886 sit at 16:00; those rows raise
`CON.RECORD_IN_HALT` at warning. SB's 02:30–11:59 window is this vendor's Chicago
normalisation of an ICE London session, not the exchange's hours.

Ship the dead-zone run-length query as the fallback for an unseeded product: it reproduced all
three shapes from the data with no reference calendar.

### 2.2.1 The 1,380 coincidence — a bug that passes its own test

Read this before writing the grouping key. It is the single most dangerous number in this
document.

A full CME-profile session is 1,380 one-minute slots. A full **calendar day**, minus the same
60-minute break, is also 1,380 — 1,440 minus 60. The two counts are identical because the
session is exactly 23 hours plus the between-session hour, i.e. 24 hours of clock. Shifting
the boundary by seven hours changes which minutes are in the session without changing how
many.

A naive `GROUP BY date(timestamp)` therefore produces **the right expected count with the
wrong membership**. Completeness reads 100%. The record count matches the fixture. Every
count-based assertion passes. And the 420 evening slots have been attributed to the wrong
trade date, so the open, the close and the high-low range of every bar are wrong.

Verified on `ESZ25`, trade date 2025-09-25, where both groupings hold exactly 1,380 bars, with
the vendor daily row as the arbiter:

| Grouping | Bars | Open | High | Low | Close |
|---|---|---|---|---|---|
| Session, 17:00 roll | 1,380 | **6697.25** | **6705.25** | **6624.25** | 6662.00 |
| Calendar date | 1,380 | 6699.75 | 6700.50 | 6624.25 | 6653.75 |
| Vendor daily row | — | **6697.25** | **6705.25** | **6624.25** | 6659.75 (settlement) |

The session grouping reproduces the vendor's open, high and low. The calendar grouping gets
the open and the high wrong while producing an identical, healthy-looking bar count.
Thirty-three calendar days in that one contract hit 1,380 as well.

Two defences, and take both:

- **Never assert on counts alone.** Assert on membership: the first and last `ts_exchange` of
  each session must equal the profile's endpoints (`17:00` and `15:59` for CME, interval-start).
  Those differ between the two groupings on every session, unlike the count.
- **Keep the boundary-recovery comparison as a live test.** Open-price agreement against the
  vendor daily files collapses under a calendar-date grouping (`specs/sample-corpus.md` §6.1).
  If that gap ever narrows, the boundary has broken.

Whenever a session length is a whole number of days, count-based completeness cannot
distinguish a correct grouping from a shifted one. Check the endpoints.

### 2.2.2 Stamping convention and calendar adjustments

Grid endpoints assume bars are **stamped at the start of their interval**, so the last bar of
a CME session is 15:59 rather than 16:00. If the source stamps at interval close the whole
grid shifts by one interval. Determine which convention the file uses — CME extremes 17:00 /
15:59 versus 17:01 / 16:00 — and record it on the batch as `ts_convention`. Getting this
backwards produces exactly two spurious findings per session.

This sample is interval-start (`specs/sample-corpus.md` §4.3). The decisive test is expiry:
every ES contract's final bar is 08:29 against a hard 08:30 CT termination.

**Holidays.** Full closures (`is_holiday`) skip the session: `expected_slots_1m = 0`, no open /
close instants. **Early closes** have a session but an unknown truncated grid:
`expected_slots_1m` is **null**, not a guessed lower count. Completeness rules refuse to
evaluate when the denominator is unavailable (`specs/dq-rules-and-scoring.md` §3). Only New
Year's Day and Christmas Day are full closures in this corpus (`specs/sample-corpus.md` §5.2).

### 2.3 Derive gaps

Anti-join actual against expected, then **run-length encode** the misses:

```sql
WITH missing AS (
  SELECT g.contract_id, g.trade_date, g.ts_utc
  FROM expected_grid g
  LEFT JOIN dq.market_record_clean m
    ON  m.contract_id = g.contract_id
    AND m.ts_utc      = g.ts_utc
    AND m.frequency   = 'minute'
  WHERE m.ts_utc IS NULL
),
runs AS (
  SELECT *,
    ts_utc - (row_number() OVER (PARTITION BY contract_id, trade_date ORDER BY ts_utc)
              * interval_len) AS run_key
  FROM missing, (SELECT INTERVAL 1 MINUTE AS interval_len)
)
SELECT contract_id, trade_date,
       min(ts_utc) AS gap_start, max(ts_utc) AS gap_end, count(*) AS missing_slots
FROM runs
GROUP BY contract_id, trade_date, run_key;
```

One missing trading day at one-minute granularity is 1,380 missing slots. Emit one finding per
contiguous gap with a `missing_slots` count (`CMP.MISSING_TIMESTAMP`). Every read of
`stage.market_record` or `dq.market_record_clean` carries a `frequency` predicate
(`specs/data-model.md` §4).

**Completeness** is `actual_count / expected_count` per session.

### 2.4 Suppression rules

Before emitting a gap finding, drop it if:

- the session is outside the contract's **liquidity** window (first and last session whose
  volume clears the floor; fall back to the listed span only when volume is unavailable) —
  `specs/dq-rules-and-scoring.md` §3. The listed span is the wrong bound.
- `session_calendar.is_holiday` — the market was shut
- the gap falls entirely inside an intra-session halt window — the market was paused
- `expected_slots_1m` is null — the denominator is unknown (early close); refuse, do not guess

These suppressions are a precondition of the completeness family, not a refinement.

---

## 3. Daily OHLCV bars

### 3.1 Definition

For each `(contract_id, trade_date)` over the chosen record basis and a single `frequency`:

| Field | Rule |
|---|---|
| `open` | the `open` value of the record with the **earliest** `ts_utc` |
| `high` | `max(high)` |
| `low` | `min(low)` |
| `close` | the `close` value of the record with the **latest** `ts_utc` |
| `volume` | `sum(volume)` |
| `open_interest` | the `open_interest` value of the record with the **latest** `ts_utc` |

Open and close are positional; high and low are extremal. `min(open)` and `max(close)` are the
canonical bug.

**`open_interest` is never summed.** It is a stock, not a flow — the count of contracts
outstanding at a point in time — so adding the minute readings together produces a number with
no meaning. Take the last reported value for the session, by the same positional path as
`close` (`arg_max` on the same tie-break struct), and leave it null when the source does not
carry the column. `mart.bar_daily` states the same rule in a column comment
(`specs/data-model.md` §5); the definition is here.

**Tie-breaking.** If two records share the earliest timestamp, break on `source_row`
ascending, so the bar is a pure function of the input file.

Vendor-supplied daily bars are not this aggregation: they are loaded as
`mart.bar_daily.source = 'vendor'` with `source_frequency = 'daily'` and
`close_convention = 'settlement'` for this corpus. The definition above is
`source = 'derived'`, `source_frequency = 'minute'`, `close_convention = 'last_trade'`.
Columns: `specs/data-model.md` §5.

The reviewer page makes this choice explicit and keeps evidence aligned with it:
`frequency=minute` means the derived source; `frequency=daily` means the supplied vendor
source. It passes the same frequency to `/v1/dq/checks` and `/v1/analytics/bars/daily`;
neither route may silently choose a different source for a selected family.

### 3.2 SQL

```sql
WITH ordered AS (
  SELECT *,
    row_number() OVER (PARTITION BY contract_id, trade_date
                       ORDER BY ts_utc ASC,  source_row ASC)  AS rn_first,
    row_number() OVER (PARTITION BY contract_id, trade_date
                       ORDER BY ts_utc DESC, source_row DESC) AS rn_last
  FROM dq.market_record_clean
  WHERE frequency = 'minute'
)
SELECT
  contract_id,
  trade_date,
  max(CASE WHEN rn_first = 1 THEN open  END) AS open,
  max(high)                                  AS high,
  min(low)                                   AS low,
  max(CASE WHEN rn_last  = 1 THEN close END) AS close,
  sum(volume)                                AS volume,
  min(ts_utc)                                AS first_ts_utc,
  max(ts_utc)                                AS last_ts_utc,
  count(*)                                   AS record_count
FROM ordered
GROUP BY contract_id, trade_date;
```

Compact form, using a struct to carry the tie-break into `arg_min` / `arg_max`. Prefer this
in shipped code; keep the `row_number()` version as the test reference:

```sql
-- verified: returns open=10.0 (row 1) not 99.0 (row 2) for a tied timestamp
SELECT
  contract_id,
  trade_date,
  arg_min(open,  {'t': ts_utc, 'r': source_row}) AS open,
  max(high)                                      AS high,
  min(low)                                       AS low,
  arg_max(close, {'t': ts_utc, 'r': source_row}) AS close,
  sum(volume)                                    AS volume
FROM dq.market_record_clean
WHERE frequency = 'minute'
GROUP BY contract_id, trade_date;
```

DuckDB compares structs field-by-field in declaration order, so `{t, r}` is
timestamp-then-row-number.

**Wrap the value in a struct too.** `arg_min` and `arg_max` skip rows whose *value* is null,
which is not this definition: §3.1 asks for the value of the earliest record, and that value
may legitimately be null. On a session whose first record has a null `open`, the bare form
returns the *second* record's open — a plausible number with no basis in the data, and one the
`row_number()` reference form does not produce. Wrapping makes the value itself non-null, so
the row is considered and the null is returned:

```sql
-- verified: returns NULL for a first record whose open is null, matching the reference form
arg_min({'v': open},  {'t': ts_utc, 'r': source_row}).v AS open,
arg_max({'v': close}, {'t': ts_utc, 'r': source_row}).v AS close
```

`open_interest` is the one field that genuinely wants the skip — "last *reported*" — so it
takes the bare form with a `FILTER (WHERE open_interest IS NOT NULL)`.

Revised 2026-09-05 (slice 3): the two forms above were previously presented as interchangeable.
They are not, in the presence of a null price.

**These semantics are tested against the vendor daily files, not just against themselves.**
That oracle — what it covers, what it does not, the coverage gate, the never-narrower range
invariant, and the claim wording ("agrees with the vendor's daily bars", never "verified
correct") — is owned by `specs/sample-corpus.md` §6. The aggregation code does not embed those
percentages. Do not assert on `close` or `volume`: vendor close is a settlement near 15:00 CT;
vendor volume is the wider figure for the same block-trade reason. Assert the explanations
instead. The oracle tests a definition chosen independently and is never used to derive one.

### 3.3 Provenance on every bar

Do not emit a bare bar. Carry, per `mart.bar_daily`:

```
record_count       -- rows that contributed
expected_count     -- from the grid, §2; null on vendor daily bars
completeness_pct   -- record_count / expected_count
finding_count      -- findings intersecting this session
max_severity       -- worst among them
basis              -- 'raw' | 'clean'
source             -- 'derived' | 'vendor'
source_frequency   -- 'minute' when derived, 'daily' when supplied
session_boundary   -- which trade-date definition produced this bar
close_convention   -- 'last_trade' | 'settlement'
volume_null_count  -- so a sum that skipped nulls is not silent
```

`session_boundary` is not padding. §2.2.1 shows that two boundaries yield bars with identical
counts and different prices; `basis` does not answer "which definition produced this number".
This vendor's minute `trading_date` is a calendar date; its daily `date` is a session date.
Record the resolved boundary in the form `session_calendar` holds it, not a bare `"CME"`.

**"Findings intersecting this session" is resolved by `dq.dq_rule.scope`**, which is a
four-value enum, so the join is a branch and not a judgement:

| Scope | Intersects a bar when |
|---|---|
| `record` | the finding's `record_id` belongs to that `(contract_id, trade_date)` |
| `session` | `contract_id`, `frequency` and `trade_date` match |
| `series` | `contract_id` matches — every session in the series |
| `file` | the finding's timestamp span overlaps the session's own span |

Match `frequency` as well as `contract_id`: a finding about the daily config is not a finding
about a bar derived from the minute tape.

The `file` row reads "the batch contributed a record to that session" in the obvious phrasing,
and that is what it means — but `dq.dq_finding` carries no `batch_id`, and `details` is
evidence and is never grouped on (`specs/data-model.md` §4). The finding's `[ts_start_utc,
ts_end_utc]` is the batch's span for that series, so overlapping it against the session's own
span asks the same question of columns that exist. Fields the finding leaves null are
wildcards: a rule that names no contract is about every contract inside its span.

`finding_count` counts **`record`- and `session`-scope findings only**. A `series`- or
`file`-scope finding is one statement about many sessions; adding it to every bar shifts the
whole trend by a constant and tells the reader nothing about which session is worse. Both
still contribute to `max_severity`, because a bar sitting inside a broken series is not
trustworthy just because the breakage was described once. One resolver serves this and the
publish gate — they ask the same question and must not answer it differently.

**The reviewer overlay is a different join.** `max_severity` stays on this envelope for the
publish gate. The UI does not key candle colour on it. Family marks for Daily OHLCV are
composed in `quality` (`GET /v1/dq/checks`, `specs/api-contract.md` §6.6): they include
`CMP.SESSION_MISSING` dates that have no bar row, and they let a minute
`CMP.MISSING_TIMESTAMP` mark the derived daily session. Do not redefine `max_severity`.

A daily bar built from 40% of its ticks is not wrong, but it is not trustworthy; shade
low-completeness candles at the point of use. Materialise under **both** bases. Vendor daily
bars leave `expected_count` / `completeness_pct` null: one supplied row is not a sample of a
one-minute grid (`specs/data-model.md` §5).

### 3.4 Edge cases

| Case | Correct behaviour |
|---|---|
| Session with a single record | Valid bar; `open`/`close` may equal `high`/`low`. Flag low completeness, do not reject. |
| Session with no records, contract active, not a holiday | No bar row. `CMP.SESSION_MISSING`. Do not emit a zero-filled bar. |
| Session with no records, holiday | No bar, no finding. |
| Outside the liquidity window | No completeness finding; the contract was not trading. |
| Volume null on some records | `sum()` skips nulls. `CMP.NULL_FIELD`; report `volume_null_count` on the bar. |
| Derived bar violates `low <= open, close <= high` | `CON.DERIVED_BAR_INVALID` — a defect escaped record-level validation. |
| Early close day | `expected_count` is null; completeness refuses. Do not invent a truncated grid. |
| Vendor-supplied daily bar whose `close` falls outside `[low, high]` | Expected when `close` is a settlement. Do **not** apply the derived-bar invariant. |

**`CON.DERIVED_BAR_INVALID` severity follows `mart.bar_daily.source`** (rule ID owned by
`specs/dq-rules-and-scoring.md` §6; method here):

| Bar provenance | Severity | Meaning |
|---|---|---|
| `source = 'derived'` | critical | A defect escaped record validation; blocks the series. |
| `source = 'vendor'` | warning | The vendor's close is a settlement and may sit outside the traded range. Flag, explain, never block. |

Without that split, ingesting this sample's daily config raises 43 critical findings on
arrival — accurate about the data, wrong about what they mean (`specs/sample-corpus.md` §7.5).
On the vendor branch the finding names the phenomenon and links to `REC.CLOSE_CONVENTION`
where one exists.

---

## 4. Rolling 15-minute VWAP

### 4.1 The formula

```
VWAP = Σ(price_i × volume_i) / Σ(volume_i)
```

Four decisions follow. They are locked.

### 4.2 Price basis — typical

For bar data the convention is the **typical price**, `(high + low + close) / 3`. Using
`close` alone discards the intra-bar range and is more sensitive to a single bad print.

Default `price_basis = typical`; `close` is available as a query parameter. Document the
basis in the UI next to the chart.

### 4.3 Rolling means a trailing time window

**(a) Trailing time window.** For each record at time `t`, VWAP over all records in
`[t − 15 min, t]`. One output per input record; a continuously updating line.

**(b) Fixed 15-minute buckets.** Resample into non-overlapping bins.

These produce different numbers. **(a) is the definition.** (b) is a display-level downsample
if the chart gets dense.

### 4.4 RANGE, not ROWS

A `ROWS BETWEEN 14 PRECEDING AND CURRENT ROW` frame takes the last 15 *records*. If the
series has missing minutes, those 15 records span more than 15 minutes and the window
silently stretches over the gap — wrong precisely where the data is worst.

Use a `RANGE` frame on the timestamp values:

```sql
RANGE BETWEEN INTERVAL 15 MINUTES PRECEDING AND CURRENT ROW
```

Inclusive at both ends: `[t − 15 min, t]`. A record exactly 15 minutes old is included.

### 4.5 Partitioning

Partition by `(contract_id, trade_date)`.

- **Never across contracts.** `ESZ25` and `ESH26` are different instruments.
- **Never across sessions.** Without `trade_date`, the first morning window reaches back
  through the maintenance break and mixes in stale pre-break prices.

Session-anchored VWAP (cumulative from the session open) is the same query with
`ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. Named as an extension, not v1.

### 4.6 SQL — `mart.vwap_15m`

VWAP is a **view**, not a table (`specs/data-model.md` §5). It reads **intraday records
only**. A daily row cannot contribute to a rolling 15-minute window; a daily-only corpus
yields an empty result, reported as *unavailable* rather than an empty series.

The shipped view is the default published line: typical price, 15-minute `RANGE`, `clean`
basis. The insights helper accepts `basis` (`raw` | `clean`) and `price_basis` (`typical` |
`close`) and runs the same window against `stage.market_record` or `dq.market_record_clean`.

```sql
CREATE VIEW mart.vwap_15m AS
SELECT
  contract_id,
  trade_date,
  ts_utc,
  'clean'   AS basis,
  'typical' AS price_basis,
  sum(px * volume) OVER w / nullif(sum(volume) OVER w, 0) AS vwap_15m,
  sum(volume)      OVER w                                 AS window_volume,
  count(*)         OVER w                                 AS window_records,
  ts_utc - first_value(ts_utc) OVER (
      PARTITION BY contract_id, trade_date ORDER BY ts_utc
  ) < INTERVAL 15 MINUTES                                 AS is_warmup
FROM (
  SELECT *, (high + low + close) / 3.0 AS px
  FROM dq.market_record_clean
  WHERE frequency = 'minute'
    AND high IS NOT NULL AND low IS NOT NULL
    AND close IS NOT NULL AND volume IS NOT NULL
)
WINDOW w AS (
  PARTITION BY contract_id, trade_date
  ORDER BY ts_utc
  RANGE BETWEEN INTERVAL 15 MINUTES PRECEDING AND CURRENT ROW
);
```

Verified on a four-row fixture at 09:00, 09:10, 09:20 and 09:25: at 09:20 the window contains
two records (09:00 has aged out); at 09:25 a zero-volume record joins the window without
changing the VWAP.

### 4.7 Zero-volume denominator

If every record in the window has zero or null volume, the denominator is zero. `nullif`
makes the result **NULL**.

Do not return 0. Do not carry the previous value forward. Do not interpolate. NULL is the
honest answer; the chart shows a **break in the line**. Forward-filling here would be the
application lying about data it does not have.

### 4.8 Warm-up

The first 15 minutes of each session have an incomplete window. Compute the value anyway and
return `is_warmup` alongside it; render that segment dashed or faded. Nulling it loses
information; presenting it unmarked overstates confidence.

### 4.9 Clean versus raw

VWAP is volume-weighted: a single fat-finger print with meaningful volume corrupts the line
for a full 15 minutes. Compute under both bases and overlay. Deduplicate before VWAP
(duplicate rows double-count volume). Order of operations: parse, dedupe, validate, exclude,
then compute — once, in the `insights` layer.

### 4.10 Numeric precision

`DOUBLE` is fine at this scale. `Σ(price × volume)` over a full session can reach ~1e10 for a
liquid contract, within double precision. A production-margining path would use `DECIMAL`.

---

## 5. Statistical outliers — MAD method

v1 optional. Rule IDs `OUT.RETURN_MAD` and `OUT.VOLUME_MAD` are owned by
`specs/dq-rules-and-scoring.md` §10 (always `info`, never auto-excluded). This section is the
method.

Use a **robust** estimator, not a z-score. Compute on **log returns**, not prices — prices
trend, returns do not:

```
r_t = ln(close_t / close_{t-1})
```

Modified z-score using median absolute deviation:

```
M_i = 0.6745 × (r_i − median(r)) / MAD(r)      flag when |M_i| > 3.5
```

`OUT.VOLUME_MAD` is the same formula on `ln(volume)`. Financial returns have fat tails, so a
3-sigma threshold flags too much in a genuinely volatile period; a single extreme print
inflates the standard deviation enough to hide itself. MAD is resistant to both.

The `0.6745` and `3.5` constants are the Iglewicz–Hoaglin choices; they live in
`dq.dq_rule.params` so they are tunable without a code change.

Run on data that has already had hard-invalid records excluded, or the invalids dominate the
distribution. An outlier is a *question*, never a verdict: any volatile window in 2021–2026
is full of legitimate extreme returns. `info` severity, never auto-excluded, always on the
analyst's review queue.
