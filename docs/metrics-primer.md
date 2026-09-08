# What the Loupe pages mean

A walkthrough of **Overview** and **Review**: what each number is, how it is
calculated, and how to read the charts.

Start at the top of each page and work down. Mocks use **example counts** so the
arithmetic is easy to follow. After **Load demo data**, your store will show
different numbers in the same shape.

**This is a reader guide, not the spec.** Exact formulas, rule IDs, and chart
rules live in `specs/`. If this document and a spec disagree, the spec wins.

The running-app map is `docs/how-loupe-works.md`. The test map is
`docs/how-tests-work.md`.

| Topic | Spec |
|---|---|
| Page layout and help copy | `specs/loupe-ui-design.md` |
| Which rules sit on which card | `specs/dq-rules-and-scoring.md` §11.8 |
| Pattern lift | `specs/dq-rules-and-scoring.md` §12 |
| Trade date, daily bars, VWAP | `specs/analytics-semantics.md` |

---

## 0. What Loupe is answering

Loupe is a first scan of **historical** futures files. It does not trade, it
does not edit the source rows, and it does not apply new rules from the UI.

Two pages, one question each:

| Page | Question | What you get |
|---|---|---|
| **Overview** (opens first) | Which loaded contracts fire which checks? | One row per contract × grain. Four headline counts. Click a row to open Review. |
| **Review** | For **one** contract, grain, and date window: can I trust this, and what does it look like? | Four check cards, daily OHLCV, 15-minute VWAP, a close-up picture, and an issues table. |

Neither page shows a quality **score**. The score still exists on the API; these
pages do not draw it.

### Words used on both pages

| Word | Meaning |
|---|---|
| **Contract** | One listed instrument, e.g. `ESZ25` (E-mini S&P, December 2025). |
| **Grain** | Which tape you are judging: **Minute** (intraday bars) or **Daily** (vendor settlement bars). They are different files. A contract that holds both appears twice on Overview. |
| **Trade date** | The date the **session closes**, not the calendar date on the timestamp. A Sunday 17:30 CT print belongs to Monday’s session. |
| **Finding** | One result from one quality rule. A finding can cover many missing minutes (see Gaps). |
| **Family** | One of the four checks on the strip: Gaps, Duplicates, Invalid values, Recurring patterns. Other rules still run; they do not headline these pages. |
| **Clean series** | Source rows with default cleaning applied (drop exact copies, exclude broken error rows). Raw files are never overwritten. |
| **Window** | Overview always uses the **full** dates held for that grain. Review uses the sidebar **From / To** trade dates, or the full held span if those are empty. |

### Units on the four checks

The same four names appear as Overview columns and as Review cards. The **unit**
tells you what was counted.

| Family | Unit | What the count is |
|---|---|---|
| Gaps | `runs` | Number of gap **findings**. One finding is one hole (a contiguous stretch of missing minutes), one thin session, or one wholly missing session — not one missing minute. |
| Duplicates | `records` | Number of duplicate **findings** (redundant copies and key conflicts). Duplicate *files* are refused at ingest and listed in the sidebar, not here. |
| Invalid values | `rows` | Number of invalid-value **findings** (a price or volume that cannot be right on its own). |
| Recurring patterns | `standing` | Number of **standing patterns** (concentrations that pass lift, support, and day-count tests). Not a finding count. |

**Zero means the check ran and found nothing** in that contract × grain × window.
**Check has not run** means validation has not finished — do not read that as
clean.

---

## 1. Overview

Overview is a corpus scan. Use it to pick a noisy contract, then open Review.

There is no contract picker, no Quality grain control, and no date range on this
page. Demo load and the ingested-file list stay in the sidebar so an empty store
can still load data.

### 1.1 Sidebar (top of the left column)

```
┌──────────────────┐
│ LOUPE            │
│ [Overview|Review]│  ← Overview is selected
│                  │
│ Demo data        │
│  711,484 records │
│  loaded.         │
│                  │
│ Load demo data   │  ← only when the store is empty
│ Inject defects   │  ← after a real load; optional
│                  │
│ Ingested files   │
│  Daily + minute  │
│   ESZ25.parquet  │
│   ESZ25.csv      │
│  Daily-only      │
│   …              │
│  Minute-only     │
│   SR3G26.csv     │
│   Converted from │
│   Parquet        │
└──────────────────┘
```

Read this column first.

| Item | What it means |
|---|---|
| **Overview \| Review** | Page switch. Not a persona selector. |
| **N records loaded** | Rows in the store after ingest. |
| **Load demo data** | Fetches the vendor sample and loads it. Real findings, nothing planted. |
| **Inject defects** | Adds one labelled synthetic file so rules that never fire on clean vendor data (exact copies, negative volume, and similar) have something to show. A warning appears while synthetic records are loaded. |
| **Ingested files** | Inventory of what is in the store, grouped by **contract coverage** (Daily + minute / Daily-only / Minute-only), not by the file’s own frequency. **Converted from Parquet** is a format fact, not a defect. |

If the store is empty, the main column says so and points at **Load demo data**.
There is no file uploader on these pages.

### 1.2 Title (top of the main column)

```
Loupe
Overview · loaded contracts × grain · full held window
```

**Full held window** means: every trade date that contract × grain actually
has. Overview does not crop dates.

If synthetic records are loaded, a notice sits under the title **before** any
table numbers. Read it first. Injected defects are labelled; they are not vendor
faults.

### 1.3 Grain filter

```
Grain:  [ All | Daily | Minute ]
```

A **view** filter on the table. It does not change Quality grain on Review.

| Choice | Rows shown |
|---|---|
| All | Every loaded contract × held grain |
| Daily | Only daily rows |
| Minute | Only minute rows |

A dual-grain contract (`ESZ25` with both files) still occupies **two** rows
when Grain is All.

### 1.4 The table

Worked example after Load demo data (illustrative counts):

```
┌──────────┬────────┬────────────┬────────────┬───────────┬───────────────┐
│ Contract │ Grain  │ Gaps       │ Duplicates │ Invalid   │ Recurring     │
│          │        │            │            │ values    │ patterns      │
├──────────┼────────┼────────────┼────────────┼───────────┼───────────────┤
│ ESZ25    │ Minute │ 5,209 runs │ 0 records  │ 1 row     │ 74 standing   │
│ ESZ25    │ Daily  │    12 runs │ 0 records  │ 4 rows    │  3 standing   │
│ ZNZ25    │ Minute │ 8,554 runs │ 0 records  │ 4 rows    │ 21 standing   │
│ SR3H26   │ Daily  │    35 runs │ 0 records  │ 4 rows    │  1 standing   │
└──────────┴────────┴────────────┴────────────┴───────────┴───────────────┘
```

Hover the **column header** (not the cell) for the one-sentence meaning of that
family. Detail sentences live on Review.

Each cell is `count` + `unit`, with thousands separators.

#### Contract

The loaded `contract_id`. Drawn heavier than the family columns because this is
the scan headline: *which instrument?*

#### Grain

`Minute` or `Daily` — the tape those four counts were computed on.

The same contract at two grains is **not** two views of one number. Minute Gaps
on `ESZ25` count missing **minute** slots against the session grid (about 1,380
expected minutes on a full CME day). Daily Gaps count missing **settlement
days**. Mixing them would double-count and mis-blame.

#### Gaps (`N runs`)

Count of open gap findings for that contract × grain over the **full** held
window.

```
Gaps count = number of findings whose rule is one of:
  CMP.MISSING_TIMESTAMP   (a contiguous hole inside a session)
  CMP.PARTIAL_SESSION     (the session is present but thinner than 95% of expected slots)
  CMP.SESSION_MISSING     (an expected non-holiday session has no records at all)
```

A high Minute Gaps count on real vendor data is common. Many deferred contracts
are sparse against a full session grid. That is missing timestamps, **not** “the
market was quiet.” Quiet minutes that *exist* as rows do not count as gaps.

`CMP.NULL_FIELD` (an empty price or volume cell) is **not** a gap. It sits on
Invalid values.

#### Duplicates (`N records`)

```
Duplicates count = number of findings whose rule is one of:
  UNQ.EXACT_DUPLICATE   (same timestamp, same OHLCV — extra copies)
  UNQ.KEY_CONFLICT      (same timestamp, different OHLCV — no safe winner)
```

On a clean vendor sample this is often **0**. Use **Inject defects** if you need
to see this card fire. Duplicate *files* never become findings: ingest refuses
them (HTTP 409) and they do not land.

#### Invalid values (`N rows`)

```
Invalid count = number of findings whose rule is:
  any VAL.*                              (price or volume impossible on its own)
  CMP.NULL_FIELD                         (a required field is empty)
  CON.HIGH_LT_LOW                        (high < low)
  CON.OPEN_OUT_OF_RANGE                  (open outside [low, high])
  CON.CLOSE_OUT_OF_RANGE                 (close outside [low, high])
```

Outliers (`OUT.*`) are **off this strip**. An unusual return is not counted as
an invalid value. “Strange” and “impossible” are different claims.

#### Recurring patterns (`N standing`)

```
Standing count = number of patterns that pass all three tests
  (computed on this contract × grain, full held window):

  1. lift        = (share of that rule’s findings in the bucket)
                   / (share of records in the same bucket)
                   ≥ 3.0
  2. support     ≥ 20 findings in that bucket
  3. distinct days ≥ 3   (except when the bucket *is* a single trade date)
```

A pattern is a **ratio**, not a pile of findings. If 50% of holes fall in one
hour, that only counts as standing if that hour does **not** also hold ~50% of
the records.

The Overview cell is the headline count only. The sentence that names the
loudest pattern is on the Review card.

#### Other cell text

| Cell | Meaning |
|---|---|
| `0 records` (or `0 runs`, `0 rows`, `0 standing`) | The check ran. Nothing in this family for that row’s window. |
| `Check has not run` | No completed validation run yet. Not a clean bill. |
| An error string | That row’s checks request failed. Other rows may still be fine. |

### 1.5 Click a row

Selecting `ESZ25` / `Minute` opens **Review** with:

- Contract = `ESZ25`
- Quality grain = Minute

The selected family stays whatever Review last had (default **Gaps**). Overview
does not pass a date window; Review’s From / To stay as they were (empty means
full span).

---

## 2. Review

Review answers two questions for **one** contract × Quality grain × date window:

1. Can I trust this? — four cards and the issues table.
2. What does it look like? — Daily OHLCV, then VWAP, then a picture of the
   **selected** family.

Main-column order is fixed: **cards → Daily OHLCV → VWAP → picture → issues**.

Worked example for the rest of this section:

- Contract `ESZ25`
- Quality grain **Minute**
- Trade dates **2025-06-02 → 2025-06-30**
- Family **Gaps** selected
- Example card counts are internally consistent (they add up)

### 2.1 Sidebar (top of the left column)

```
┌──────────────────┐
│ LOUPE            │
│ [Overview|Review]│  ← Review is selected
│                  │
│ Contract         │
│  [ESZ25     ▾]   │
│                  │
│ Quality grain    │
│  [Minute|Daily]  │  ← only if both tapes exist
│                  │
│ Trade dates      │
│  From 2025-06-02 │
│  To   2025-06-30 │
│                  │
│ Demo data        │
│ Inject / files   │  ← same inventory as Overview
└──────────────────┘
```

| Control | What it does to the numbers |
|---|---|
| **Contract** | Every card, both charts, the picture, and the issues table use this one id. |
| **Quality grain** | Minute (default when both exist): cards and OHLCV read the **minute tape**; daily candles are **derived** from those minutes. Daily: cards and OHLCV read the **vendor daily** file. Changing family never changes grain. A single-grain contract has no switch — only a caption. |
| **From / To** | Trade-date filter. Empty = all held dates for that contract × grain. Changing these resets chart zoom. |

### 2.2 Title (top of the main column)

```
Loupe
ESZ25 · Minute quality grain · 2025-06-02 → 2025-06-30
```

If From / To are empty, the date part is omitted. The header always names the
**resolved** grain.

### 2.3 Four family cards

The cards **are** the family selector. There is no separate Check row. Click a
card to change the overlay, the OHLCV legend, the picture, and the issues table.
The other three counts stay visible.

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐
│ Selected     │ │              │ │              │ │                    │
│ Gaps         │ │ Duplicates   │ │ Invalid      │ │ Recurring patterns │
│              │ │              │ │ values       │ │                    │
│ 20 runs      │ │ 4 records    │ │ 12 rows      │ │ 2 standing         │
│              │ │              │ │              │ │                    │
│ 18 session-  │ │ 3 exact      │ │ 8 prices     │ │ 82% of missing-    │
│ open holes · │ │ copies ·     │ │ · 4 volumes  │ │ timestamp findings │
│ 2 sessions   │ │ 1 key        │ │              │ │ fall in the 17:00- │
│ absent       │ │ conflict     │ │              │ │ 18:00 hour, …      │
└──────────────┘ └──────────────┘ └──────────────┘ └────────────────────┘
```

Help attaches to the **count line** (`20 runs`), not the title.

**Type hierarchy:** the count is the lead; the line under it is a breakdown or
a narrative, not a second KPI.

#### Gaps card

**Count** = gap findings in this contract × grain × date window.

**Detail** splits that count:

```
session-open holes = findings with
    CMP.MISSING_TIMESTAMP  or  CMP.PARTIAL_SESSION

sessions absent    = findings with
    CMP.SESSION_MISSING

count = holes + absent
```

In the mock: `18 + 2 = 20 runs`.

How a **hole** is built (minute grain):

1. Build the expected minute grid for that session (exchange-local open to
   close, skipping the maintenance break and holidays).
2. Find minutes that should exist and do not.
3. Group neighbouring missing minutes into one **run**.
4. Write **one** finding. `affected_rows` = how many minutes are in that run.

A session that lost four minutes at the 17:00 CT open is **1 run**, not 4.
That is why the unit is `runs`.

How an **absent session** is built:

- The calendar says this trade date should trade.
- It is not a holiday, and the contract is inside its liquidity window.
- There are **no** records that day at this grain.
- One finding. `affected_rows` = expected slots (1,380 at minute; 1 at daily).

Loupe does **not** invent a zero-priced bar for that day.

#### Duplicates card

**Count** = duplicate findings in the window.

**Detail:**

```
exact copies   = UNQ.EXACT_DUPLICATE findings
key conflicts  = UNQ.KEY_CONFLICT findings
count          = exact + conflicts
```

In the mock: `3 + 1 = 4 records`.

| Rule | Trigger | What cleaning does |
|---|---|---|
| Exact copy | Same key **and** same OHLCV | Keep the lowest `source_row`; drop the extras (`dedupe_drop`). |
| Key conflict | Same `(contract, grain, timestamp)`, **different** OHLCV | Exclude **every** row in the clash. There is no winner inside one file. |

Compared **within a grain**, never across. A daily row and 1,380 minute rows for
the same session are not duplicates.

#### Invalid values card

**Count** = invalid-value findings in the window.

**Detail** splits by subject:

```
volumes = findings that accuse volume
          (negative / non-integer / zero-with-range / extreme volume,
           or a null volume cell)

prices  = all other findings on this card
          (bad prices, null price cells, high < low, open or close
           outside [low, high])

count   = prices + volumes
```

In the mock: `8 + 4 = 12 rows`.

Each of these findings is typically **one row**. Severity decides cleaning:
`error` / `critical` exclude the row from the clean view; `warning` flags only
(`VAL.OFF_TICK_PRICE` is always flag-only).

#### Recurring patterns card

**Count** = standing patterns in this contract × grain × window (same three
tests as Overview, but cropped to From / To).

**Detail** = the narrative of the **highest-lift** pattern, or “No standing
pattern in this window”.

The narrative is a filled-in sentence, not a model. Example:

> 82% of missing-timestamp findings fall in the 17:00-18:00 America/Chicago
> hour, across 18 sessions.

That does **not** mean 82% of minutes are missing. It means: of the
missing-timestamp findings that exist, 82% of them sit in that hour.

Worked lift (same mock hour):

```
share of findings in 17:00–18:00  = 0.82
share of records  in 17:00–18:00  = 0.04
lift                              = 0.82 / 0.04 = 20.5

20.5 ≥ 3.0, support ≥ 20, days ≥ 3  →  standing
```

### 2.4 Daily OHLCV

```
Daily OHLCV
Derived from minute · Minute quality grain · selected family. Rule IDs stay off the candle.

        ▲              ▲                    ╎absent╎
   █    █    █    █    █    █         █          █    █
   █    █    █    █    █    █         █          █    █
  vol ▁▂▃▅▇▅▃▂▁  ▁▂▃▄▅▃▂▁                    ▁▂▃▄▂

Legend: Session-open hole · Settlement never arrived
Drag dates to pan/zoom. Double-click to reset.
```

| Caption fragment | Meaning |
|---|---|
| **Derived from minute** | Each candle is aggregated from that session’s **minute** rows (Quality grain = Minute). |
| **Supplied daily** | Each candle is the vendor’s daily bar (Quality grain = Daily). |
| **selected family** | Marks on the chart match the card you clicked, only. |

The candles are the **clean** series.

#### How a derived daily candle is calculated

For one `(contract, trade_date)` from minute rows:

| Field | Rule |
|---|---|
| Open | `open` of the **earliest** minute (`ts_utc`, then `source_row`) |
| High | `max(high)` |
| Low | `min(low)` |
| Close | `close` of the **latest** minute |
| Volume | `sum(volume)` |

Open and close are positional (first / last print). High and low are extremes.
`min(open)` and `max(close)` would be the wrong bar.

Vendor daily **close** is a **settlement** (often near 15:00 CT). Derived close
is **last trade**. They are not the same number and are not tuned to match.

A session with **no** records produces **no** candle. Absence is a dashed
column with an on-chart **absent** label — never a zero bar.

A holiday with no trading is not an absent settlement: no candle, no finding.

#### Marks (selected family only)

The chart does **not** colour candles by “worst severity”. It only paints the
family you selected.

| Selected family | What you see |
|---|---|
| Gaps | Triangle / pin on a session that has a hole. Dashed **absent** column if the session never arrived. The candle body stays the clean series — the defect is missing time, not a bad close. |
| Duplicates | Pin on the kept timestamp. Body colour unchanged. |
| Invalid values | Paint that candle. Volume defects sit on the **volume** pane. |
| Recurring patterns | Shaded band on every session that participates in the pattern, including absences that belong to it. |

#### Hover

Candles and markers show **date, open, high, low, close**, and **status**:

| Status | Meaning |
|---|---|
| `clean` | No selected-family mark on this date. |
| `gap: session-open hole` | Hole or thin session that day. |
| `gap: session missing` | Expected session never arrived. |
| `duplicate` | A kept duplicate timestamp that day. |
| `invalid value` / `volume defect` | Invalid-values family mark. |
| `pattern member` | This date sits in the standing pattern. |

Absent columns have no OHLC. Volume hover is date, volume, and status — not
internal colour-field names.

#### Zoom

OHLCV and the volume pane share one x-axis (trade date). Drag to pan or zoom;
double-click to reset. Changing contract, Quality grain, or From / To resets
zoom. Changing **family** keeps the same zoom.

### 2.5 Rolling 15-minute VWAP

```
Rolling 15-minute VWAP

     ────────●●●●────  ╳  ────●●●●●────────
                         ↑
                    named break
                    (volume dropped)
```

VWAP always comes from the **minute tape**. A daily row cannot go into a
15-minute window.

#### How each point is calculated

For each minute `t` in a session:

```
price_i  = (high_i + low_i + close_i) / 3     (typical price)

VWAP(t)  = Σ (price_i × volume_i) / Σ volume_i

           over all minutes in the same contract and trade date
           whose timestamp is in [t − 15 minutes, t]
```

Locked details that change the number if you get them wrong:

| Choice | What Loupe does | What it is not |
|---|---|---|
| Window | Trailing **15 minutes of clock time** | The last 15 *rows* (that would stretch across a gap) |
| Partition | One session (`contract` + `trade_date`) | Mixing Monday morning with Friday’s close |
| Empty volume | `VWAP` is **null** — the line **breaks** | 0, or the previous value carried forward |
| First 15 minutes | Still computed, flagged as warm-up | Dropped or treated as a full window |

Duplicates are removed **before** VWAP so copied volume is not counted twice.
The line on this page is the **clean** basis.

#### Marks and refusals

| Situation | What the panel does |
|---|---|
| Gaps or patterns selected | Names the break (cross) where window volume was dropped. Patterns also shade the concentrating hour. |
| Duplicates selected | Usually no extra marks on the line. |
| Invalid values selected | Marks a break only if cleaning dropped that window. |
| Daily-only contract | Panel stays. Copy: **Needs minute bars.** No fake 15-*day* VWAP. |
| Quality grain is Daily, but minute rows exist | Line still draws, labelled **Minute tape · context only for Daily quality grain**. Family marks on VWAP are suppressed so daily findings do not decorate a minute line. |

VWAP has its **own** zoom (intraday timestamps), independent of OHLCV.

### 2.6 Picture of the selected family

Lives **under** VWAP. Same family as the selected card. Rule IDs, if shown, are
a **caption**, never the headline.

#### Gaps — ribbon of minutes

```
Picture of gaps
Four consecutive minute slots missing at the session open.
CMP.MISSING_TIMESTAMP

  17:00  17:01  17:02  17:03  17:04  17:05  …
    □      □      □      □      ■      ■
  missing missing missing missing present present
```

Each cell is one expected minute around the hole: present vs missing.

If the picture is an **absent session**, there is no ribbon. The copy says the
settlement never arrived; Loupe did not invent a bar.

#### Duplicates — kept vs dropped

A two-row table: the row that was **kept** and the row that was **dropped**,
same timestamp.

#### Invalid values — the broken cell

Names the **field** that failed (`volume`, `close`, …). A volume rule never
falls back to showing `close`. The table is the accused source row or bar, with
its evidence grain (minute vs daily).

#### Recurring patterns — findings vs exposure

```
Picture of recurring patterns
Showing 1 of 2 standing patterns
CMP.MISSING_TIMESTAMP

Share (%)
  80 ┤  Findings ●
     │              lift 20.5×
  40 ┤
     │  Records (exposure) ■
   0 ┼────────────────────────
        16:00    17:00    18:00     (hour of day)
```

One chart = one `(rule, dimension)` group. It does not mix another rule onto
the same axes.

| Series | Meaning |
|---|---|
| **Findings** | That bucket’s share of this rule’s findings. |
| **Records (exposure)** | That bucket’s share of the records. |
| **lift** | findings share / records share. |

Over-representation is findings share **above** record exposure. Inclusion is
the standing threshold, not raw count.

When the selected family has count **0**, the picture says the check ran and
found nothing. It does not draw an empty ribbon that looks like a full session.

### 2.7 Issues in selected family

Only the **selected** card. One row per issue type, not one row per finding.

```
Issues in selected family · Gaps

┌──────────────────┬──────┬─────────┬──────────────────────────┐
│ What             │ Days │ Records │ What we did              │
├──────────────────┼──────┼─────────┼──────────────────────────┤
│ Missing grid     │   18 │      72 │ Flagged; not auto-dropped│
│ slots            │      │         │                          │
│ Session absent   │    2 │   2,760 │ Flagged; not auto-dropped│
└──────────────────┴──────┴─────────┴──────────────────────────┘
```

In this mock the 18 holes are all missing-timestamp runs (no partial-session
row). `18 findings + 2 absent = 20 runs` on the card. **Records** still sums
hole lengths, not findings: `18 × 4 missing minutes = 72`.

Hover the **column header** for help. The What / What we did *cells* are already
the explanation.

| Column | How it is calculated |
|---|---|
| **What** | Catalogue name of the rule (`dq.dq_rule.name`), or the pattern narrative. Not a rule ID. |
| **Days** | Distinct `trade_date`s in this window that carry that issue. |
| **Records** | Sum of `affected_rows` across those findings (or pattern `support` on the patterns card). |
| **What we did** | Default cleaning from the changelog, aggregated. This page does not apply a new rule. |

| What we did | Meaning |
|---|---|
| `Flagged; not auto-dropped` | The rule fired; default policy left the rows in the clean view (typical for `warning`). |
| `dropped N records` | Exact duplicates: extras removed, lowest `source_row` kept. |
| `excluded N records` | Error/critical rows removed from the clean view. Raw rows still exist. |
| `Reported; not applied` | A standing pattern. Insights only; nothing was cleaned because of it. |

There is no Apply, Dismiss, or Override control. v1 is report-only for the
user. The engine still applies its default cleaning to build the clean series
you see on the charts.

If the table is empty and the card is 0, the page says the check ran and found
nothing.

---

## 3. What you will not see (and why)

| Absent on these pages | Why |
|---|---|
| A 0–100 score | Review and Overview do not draw it. Cards and charts are the evidence. |
| Outliers as a fifth card | `OUT.*` is diagnostic (“unusual”), not “wrong”. Off the strip. |
| Timeliness / roll / reconciliation cards | Those rules still run. They do not headline Overview or Review. |
| Raw vs clean toggle | Charts are the clean series. |
| Apply / edit / override | Report-only. **What we did** is the changelog of default cleaning. |

Reconciliation (vendor daily vs derived daily) still matters for dual-grain
contracts. It does not get its own card on these two pages.

---

## 4. Formula sheet

Scoped to **one contract, one grain, one date window** (Overview: window = full
held span).

### Family counts

```
Gaps          = count(findings in {MISSING_TIMESTAMP, PARTIAL_SESSION, SESSION_MISSING})
Duplicates    = count(findings in {EXACT_DUPLICATE, KEY_CONFLICT})
Invalid       = count(findings in VAL.* ∪ {NULL_FIELD, HIGH_LT_LOW,
                                          OPEN_OUT_OF_RANGE, CLOSE_OUT_OF_RANGE})
Patterns      = count(standing patterns)
```

### Pattern lift

```
share_of_findings(bucket) = findings in bucket / all findings for that rule
share_of_records(bucket)  = records  in bucket / all records  in scope

lift = share_of_findings / share_of_records

standing when:
  lift ≥ 3.0
  support ≥ 20
  distinct days ≥ 3   (not required when the bucket is itself a trade date)
```

Both shares use the **same** grain. Minute findings are never divided by daily
records.

### Derived daily OHLCV

```
open   = open  of first minute  (by ts_utc, then source_row)
high   = max(high)
low    = min(low)
close  = close of last minute
volume = sum(volume)
```

No rows that session → no candle.

### Rolling 15-minute VWAP

```
typical_i = (high_i + low_i + close_i) / 3

VWAP(t) = Σ typical_i × volume_i  /  Σ volume_i
          for minutes in the same session with ts in [t − 15 min, t]

if Σ volume_i = 0  →  null (break the line)
```

### Issues table

```
Days     = distinct trade_date of findings (or pattern.distinct_days)
Records  = sum(affected_rows)               (or pattern.support)
```

For a missing-timestamp finding, `affected_rows` is the length of that hole in
minutes, not `1`.

---

## 5. A short path through the UI

1. Open Loupe. You land on **Overview**.
2. If the store is empty, **Load demo data**. Wait for the table.
3. Read **Grain** and the four headline counts. A large Minute **Gaps** figure
   is usually sparse sessions vs the expected grid.
4. Click a noisy row (contract + grain).
5. On **Review**, confirm the header: contract, grain, dates.
6. Read all four cards. Click **Gaps**. Zero is a real answer.
7. Read Daily OHLCV: clean candles, family marks, **absent** if a session never
   arrived. Hover a mark and read **status**.
8. Read VWAP: breaks are missing window volume, not a drawn-through guess.
   Daily-only contracts keep the panel and say they need minute bars.
9. Read the picture — the close-up of the same family.
10. Read **Issues in selected family**: What / Days / Records / What we did.
    Records are affected rows, not a second copy of the card count.

Then click **Duplicates**, **Invalid values**, and **Recurring patterns** in
turn. The charts and picture change; the four counts do not.
