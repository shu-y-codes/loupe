# Loupe UI design

Revised 2026-09-07: v1 sidebar ingest is **Load demo data**; after a load the sidebar lists
ingested batches and marks demo CSVs converted from Parquet. Capability preview is not a
sidebar panel.

## UI philosophy
The design of the UI should be intuitive: the Summary module presents a view that answers the User's primary question at a high level and the Specifics table allows them to have a closer look.

Summary: what is available, what is ok, what needs your attention
Specifics: why your attention is needed, how do you address it

It provides

## Tooltips

Help on **named boxes** (KPI tiles and column headers), not on every grid cell.
One sentence, in that persona’s language. Streamlit: `st.metric(..., help=...)`,
dataframe column `help`, chart caption. Not a glossary overlay.

**Attach help**

- Headline KPIs: Score, Book hit, Completeness, Settlement trend, With warnings
- Module jargon: lift, changelog, raw neighbourhood, VWAP “needs minute bars”
- Column headers: Warning, Closing-day, Severity

Examples: Risk completeness — “Share of expected settlement sessions that arrived.”
Analyst lift — “How much more often this issue shows up in this bucket than overall.”
Settlement trend — sparkline of settlement reliability over trade dates (not a price
histogram). "Settlement reliability" is defined under Risk → Summary below; it is daily
completeness, not a new metric.

**Skip**

- Why / Impact / Address rows and the findings What column — those cells are the explanation
- Trader candle bodies once changelog marks are labelled on the chart
- Rule IDs or expected-effect JSON in a hover

## User motivations

| | Risk | Trader | Analyst |
|---|---|---|---|
| Default grain | Many contracts | One contract | One contract, all issues |
| Primary question | Is settlement trustworthy, and how much of the book is hit? | Is this series usable for charts / backtest? | What is broken, and should we cleanse or keep it? |
| Analytics they will actually look at | Daily OHLCV, raw vs clean | Daily OHLCV + 15-min VWAP | Both, plus daily-vs-minute when both exist |
| DQ they will actually look at | Score, trend, closing-day callouts, % affected | Score, warnings, changelog | Findings, patterns, suggestions (report-only) |
| Depth they will not want | Tick drill-down, outlier hunting | Rule authoring, portfolio heatmaps | None — this is the deep view |


## Discussion
### Risk manager
Based on the `persona motivations` table, the Risk manager's primary question is "settlement trustworthy, and how much of the book is hit?"

#### Summary module
These are contracts in the portfolio we are assessing for settlement-trustworthiness.
Here's what's trustworthy, here's what needs your attention.
This is the trend.

#### Specifics module
Here is a contract you've selected.
Here is a reason it needs your attention.
Here's how much we're impacted.
Here is a suggestion based on reason and impact.

## Wireframe

Same page for every persona. Sidebar holds persona, trade dates, and demo ingest.
Summary answers the primary question. Selecting a row drives Specifics.
Specifics is a table first (why, impact, what to do); charts sit under it only
when that persona will actually look at them.

Risk manager is filled in below. Trader and analyst keep the boxes and swap
contents per the motivations table.

### Sidebar

Persona, trade dates, and demo ingest. There is **no file uploader**.

**Load demo data** is the only v1 UI ingest path. Locked decision 9 already named
the button; it is chrome here, not only a sentence in the solution brief. It posts
files already on local disk to `POST /v1/ingest/batches` with `origin=demo`
(`specs/api-contract.md` §4.3). Arbitrary CSV or Parquet ingest remains an API
path. The UI is not a second way to do the same thing.

**Ingested files** appear after a successful load. The list is `GET /v1/ingest/batches`
— filename, format, origin — inventory of what the store holds, not a second ingest
control and not a walk of `data/samples/`. Converted rows show as CSV; the Parquet
they replaced is not in the load (`specs/sample-corpus.md` §8).

**CSV mark.** Rows with `origin = demo` and CSV (`file_format` or suffix) are marked
**converted from Parquet**, so a reviewer can see the CSV half of "accept CSV or
Parquet" without opening a directory. That copy is a format fact, not a defect.
After injection the planted file is also a CSV; that mark is the synthetic
disclosure (`origin = injected`), not this one. Do not key the conversion mark off
"any CSV".

**Empty store.** Summary says no contracts are loaded and points at Load demo data.
A failed fetch is answered in place and does not point at an uploader.

**Capability preview is not on this page.** `POST /v1/ingest/preview` stays as an
API dry run. Demo load skips per-file preview (`validate=False`, then one
corpus-wide run). Unavailable capabilities are disclosed in place on the dashboard
after load — VWAP keeps its panel and says "needs minute bars"; a daily-only score
caption names the missing minute tape. There is no pre-commit sidebar matrix.

### Page

```
┌──────────────────┬──────────────────────────────────────────────────────────┐
│ LOUPE            │                                                          │
│                  │  SUMMARY                                                 │
│ Persona          │  what is available · what is ok · what needs attention   │
│  ( ) Risk        │                                                          │
│  ( ) Trader      │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────────────┐  │
│  ( ) Analyst     │  │ Score   │ │ Book    │ │ Completeness│ │ Settlement │  │
│                  │  │ 72      │ │ 4 / 18  │ │ 94%         │ │ ▁▂▃▅▄▃▂   │  │
│ Trade dates      │  └─────────┘ └─────────┘ └─────────┘ └────────────────┘  │
│  [2025-01-02]    │                                                          │
│  [2025-12-19]    │  Contracts · worst first · click a row → Specifics       │
│                  │  ┌────────┬────────┬─────────┬───────┬─────────────────┐ │
│ Demo data        │  │ Status │ Root   │ Contract│ Score │ Closing-day     │ │
│ Inject defects   │  │ ATTN   │ ZC     │ ZCZ25   │ 41    │ close outside HL│ │
│                  │  │ ATTN   │ CL     │ CLG26   │ 58    │ gap at EOD      │ │
│ Ingested files   │  │ OK     │ ES     │ ESZ25   │ 96    │ —               │ │
│  ESZ25.parquet   │  └────────┴────────┴─────────┴───────┴─────────────────┘ │
│  parquet · demo  │  cmp+val+con+unq+tim · no reconciliation for 2 contracts │
│  SR3G26.csv      │                                                          │
│  csv · demo      │                                                          │
│  from Parquet    │  SPECIFICS                                               │
│                  │  why attention is needed · how you address it            │
│                  │                                                          │
│                  │  Selected: ZCZ25                    [ + contract ]       │
│                  │                                                          │
│                  │  ┌────────────────┬────────────────┬───────────────────┐ │
│                  │  │ Why            │ Impact         │ Address           │ │
│                  │  │ Close outside  │ 12% bars       │ Review settlement │ │
│                  │  │ H–L on         │ excluded from  │ vs range; do not  │ │
│                  │  │ 2025-12-12     │ clean view     │ auto-exclude      │ │
│                  │  └────────────────┴────────────────┴───────────────────┘ │
│                  │                                                          │
│                  │  Daily OHLCV (quality on the candle)   Raw vs clean      │
│                  │  ┌─────────────────────────────┐  ┌───────────────────┐  │
│                  │  │ ▌▌  ▌▌▌ ▌  ▌                │  │ raw ──  clean - - │  │
│                  │  └─────────────────────────────┘  └───────────────────┘  │
│                  │  no tick log · no outlier hunting                        │
└──────────────────┴──────────────────────────────────────────────────────────┘
```

### Summary module

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SUMMARY                                                                     │
│                                                                             │
│  Headline = primary question at book grain                                  │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐             │
│  │ overall DQ score │ │ how much is hit  │ │ completeness %   │   trend     │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘             │
│                                                                             │
│  Inventory = what is available, tagged ok vs attention                      │
│  ┌─────────┬──────────┬─────────┬──────────────────────────────┐            │
│  │ status  │ contract │ score   │ callout (one line)           │            │
│  ├─────────┼──────────┼─────────┼──────────────────────────────┤            │
│  │ ATTN    │ …        │ …       │ why it is in this list       │            │
│  │ OK      │ …        │ …       │ —                            │            │
│  └─────────┴──────────┴─────────┴──────────────────────────────┘            │
│                                                                             │
│  Risk:    all loaded contracts, worst first, closing-day callout            │
│  Trader:  grouped/sorted by name, score + warning (no go/no-go column)      │
│  Analyst: grouped by name, sorted by score then name                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Specifics module

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SPECIFICS                                                                   │
│  filter: contract(s) · trade dates   (score / metrics / log recompute)      │
│                                                                             │
│  Table (always)                                                             │
│  ┌────────────────────────┬────────────────────────┬──────────────────────┐ │
│  │ Why                    │ Impact                 │ Address              │ │
│  │ reason attention       │ how much is affected   │ suggestion / action  │ │
│  │ is needed              │                        │                      │ │
│  └────────────────────────┴────────────────────────┴──────────────────────┘ │
│                                                                             │
│  Under the table, only what that persona will look at                       │
│                                                                             │
│  Risk     closing-day callouts · % excluded · raw vs clean daily close      │
│           daily OHLCV with quality on the candle                            │
│           no tick drill-down, no outlier hunting                            │
│                                                                             │
│  Trader   one contract · warnings · changelog                               │
│           daily OHLCV + 15-min VWAP when minute data exists                 │
│           changelog actions marked on the chart; click row ↔ mark           │
│           VWAP refused in place if daily-only                               │
│           no rule authoring, no portfolio heatmap                           │
│                                                                             │
│  Analyst  findings log (read-only) · patterns · suggestions (text)          │
│           findings/suggestions are reported, not applied                    │
│           raw neighbourhood of selected finding (highlight, not edit)       │
│           charts as a diagnostic; daily-vs-minute when both exist           │
│           this is the deep view                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### By persona

Same two modules. Headline metrics, list sort, Specifics table columns, and
charts under the table change with the persona.

#### Risk manager

Primary question: is settlement trustworthy, and how much of the book is hit?

**Summary**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SUMMARY · risk                                                              │
│                                                                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │
│  │ DQ score     │ │ Book hit     │ │ Completeness │ │ Settlement trend   │  │
│  │ 72           │ │ 4 of 18      │ │ 94% sessions │ │ ▁▂▃▅▄▃▂            │  │
│  │              │ │ need attn    │ │              │ │                    │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────────────┘  │
│                                                                             │
│  Loaded contracts · worst first                                             │
│  ┌────────┬────────┬─────────┬───────┬────────────────────────────────────┐ │
│  │ Status │ Root   │ Contract│ Score │ Closing-day                        │ │
│  ├────────┼────────┼─────────┼───────┼────────────────────────────────────┤ │
│  │ ATTN   │ ZC     │ ZCZ25   │ 41    │ close outside H–L  2025-12-12      │ │
│  │ ATTN   │ CL     │ CLG26   │ 58    │ missing EOD bar                    │ │
│  │ ATTN   │ GC     │ GCG26   │ 61    │ duplicate settlement               │ │
│  │ ATTN   │ SB     │ SBK26   │ 67    │ off-tick close                     │ │
│  │ OK     │ ES     │ ESZ25   │ 96    │ —                                  │ │
│  │ OK     │ ZN     │ ZNZ25   │ 98    │ —                                  │ │
│  └────────┴────────┴─────────┴───────┴────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Status is severity, not a score cut.** A contract is `ATTN` when it has **any open finding
of severity `error` or `critical`**, and `OK` otherwise. **Book hit** counts the `ATTN` rows.

No score threshold is used, deliberately. `specs/dq-rules-and-scoring.md` §11.5 has the score
as a navigation index and not a grade, and a cut at 70-or-80-or-90 turns it into one while
answering a question the severities already answer exactly. `error` and `critical` are also
the severities default cleaning acts on (§14), so `ATTN` means "something here was excluded
or blocked", which is what a risk manager is asking. A contract can therefore sit at a
middling score and read `OK` — many low-severity findings — and that is the honest answer,
not a rounding error.

**Settlement trend is daily completeness per trade date.** "Settlement reliability" is not a
new metric: for a daily-frequency contract one expected record *is* one expected settlement
session, so the Risk completeness tooltip above ("share of expected settlement sessions that
arrived") and the `completeness` dimension of §11.1 are the same quantity. The sparkline is
that dimension over `trade_date`, restricted to `frequency = 'daily'` —
`mart.dq_metric_daily` already stores it per contract × date × frequency × dimension, and
`GET /v1/dq/metrics?group_by=day` gains a `dimension` filter to select it (the unfiltered
call averages the dimensions together).

A contract held only at minute grain has no daily records and so no settlement trend. That is
the same boundary as §11.6's closing-day callout and holds for the same reason: settlement
lives in the daily file.

**Every surface that shows a score says which dimensions were in scope.** A six-dimension
score is better evidenced than a five-dimension one and is not the same measurement
(`specs/dq-rules-and-scoring.md` §11.3), so a bare `96` is not self-describing. Where a score
appears, `scope_signature` and `dimensions_not_in_scope` travel with it. Equal signature means
comparable; unequal means the page must say so — in two places, because they answer different
questions:

- **The headline caption** states what the book's scores were measured over, and what that
  therefore cannot tell you. Enough on its own when every contract shares a signature: the
  limitation is absolute and applies to all of them equally.
- **A mark on the score cell** (`†`), when contracts *differ*. The inventory sorts scores
  against each other in one column, which is the most persuasive invitation there is to
  compare them, and a caption cannot say which row is the five-dimension one. The mark is
  explained once beneath the table, naming the affected contracts, and is absent entirely
  when scope is uniform so it never becomes furniture.

**For Risk this is not a footnote; for the others it is.** Reconciliation is the only family
that can catch a settlement file that is internally perfect and still wrong (§9), and Risk is
the one persona whose primary question depends on it — so their disclosure names the
consequence and the fix ("load the minute tape to reconcile it"). Trader and Analyst are told
the same fact in the terms it matters to them: cross-frequency checks did not run, and scores
with different signatures are not directly comparable. Neither is being told their view is
invalid, because it is not.

**When no daily records are loaded at all, both panels say so.** The trend tile and the
inventory each state "No daily records loaded", the way the VWAP panel states "needs minute
bars" rather than rendering an empty chart. An empty Closing-day column is ambiguous between
*nothing is wrong with the close* and *we cannot see the close from here*, and on a
minute-only corpus it is always the second — so the page must not let a column of em dashes
read as a clean bill of health. Risk loses two of its five columns and one of its four tiles
on such a corpus, which is correct but needs saying out loud.

**A daily finding states whether the tape corroborates it.** Where a contract holds both
grains, the **Why** cell carries the corroboration state of `specs/dq-rules-and-scoring.md`
§8.7 alongside the finding, because it changes what the reader should do about it:

```
Why
Close outside H–L  ZCZ25  2025-12-12
  range confirmed against the tape — the settlement sits 2 ticks above the high
```
```
Close outside H–L  ZCZ25  2025-12-12
  range disputed — the tape found prints 3 ticks above the stated high
```
```
Close outside H–L  ZCZ25  2025-12-12
  not corroborated — no minute tape for this session
```

The state arrives on the finding itself (`specs/api-contract.md` §6.2), so the cell renders
what it was given and computes nothing. The first two are opposite instructions wearing the
same finding: one says the settlement
behaved like a settlement against a range you can trust, the other says the range itself is
wrong and the close may be sound. The third says neither, and says it rather than implying
the first. Reconciliation earns its place on the Risk screen here — qualifying a callout —
and not by adding one to the Closing-day column (§11.6).

**Specifics** — multi-select allowed; no tick log, no outlier hunting.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SPECIFICS · risk                                                            │
│  Selected: ZCZ25  ZCK26          trade dates [2025-01-02 → 2025-12-19]      │
│                                                                             │
│  ┌────────────────────────┬────────────────────────┬──────────────────────┐ │
│  │ Why                    │ Impact                 │ Address              │ │
│  ├────────────────────────┼────────────────────────┼──────────────────────┤ │
│  │ Close outside H–L      │ 12% of bars excluded   │ Review vs range;     │ │
│  │ ZCZ25  2025-12-12      │ from clean view        │ do not auto-drop     │ │
│  │ Gap at session close   │ 1 of 2 contracts       │ Keep for mark; flag  │ │
│  │ ZCK26  2025-03-14      │ missing a settlement   │ the session          │ │
│  └────────────────────────┴────────────────────────┴──────────────────────┘ │
│                                                                             │
│  Daily OHLCV · quality on the candle          Raw vs clean close            │
│  ┌────────────────────────────────────────┐  ┌───────────────────────────┐  │
│  │           ▌  ▌▌   ▌▌▌  ▌               │  │  raw ────────             │  │
│  │        ▌▌▌▌          ▌                 │  │  clean - - - -            │  │
│  └────────────────────────────────────────┘  └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Trader

Primary question: is this series usable for charts / backtest?

**Summary**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SUMMARY · trader                                                            │
│                                                                             │
│  ┌──────────────┐ ┌──────────────┐                                          │
│  │ Contracts    │ │ With warnings│                                          │
│  │ 18           │ │ 3            │                                          │
│  └──────────────┘ └──────────────┘                                          │
│                                                                             │
│  Loaded contracts · grouped / sorted by name                                │
│  ┌────────┬─────────┬───────┬─────────────────────────────────────────────┐ │
│  │ Root   │ Contract│ Score │ Warning                                     │ │
│  ├────────┼─────────┼───────┼─────────────────────────────────────────────┤ │
│  │ CL     │ CLG26   │ 58    │ missing EOD bar                             │ │
│  │ ES     │ ESH26   │ 91    │ —                                           │ │
│  │ ES     │ ESZ25   │ 96    │ 3 session-open gaps                         │ │
│  │ GC     │ GCG26   │ 88    │ —                                           │ │
│  │ ZC     │ ZCZ25   │ 41    │ close outside H–L                           │ │
│  │ ZN     │ ZNZ25   │ 98    │ —                                           │ │
│  └────────┴─────────┴───────┴─────────────────────────────────────────────┘ │
│  no portfolio heatmap · score carries go/no-go; warning is the one-liner    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Specifics** — one contract; VWAP refused in place if daily-only.

Chart is the **clean** series (what they would backtest). Changelog actions that
changed a bar in the window are marks on that timestamp. Click a row to highlight
the mark; click a mark to highlight the row. Raw is a ghost only where it
disagrees. VWAP breaks (`NULL`) where cleaning dropped window volume — a gap,
not a connected line.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SPECIFICS · trader                                                          │
│  Contract: ESZ25 ▾           trade dates [2025-06-02 → 2025-06-30]          │
│  Score 96 · completeness 99% of expected minute slots in this window        │
│                                                                             │
│  ┌────────────────────────┬────────────────────────┬──────────────────────┐ │
│  │ Why                    │ Impact                 │ Address              │ │
│  ├────────────────────────┼────────────────────────┼──────────────────────┤ │
│  │ 3 session-open gaps    │ VWAP undefined for     │ Use clean view;      │ │
│  │                        │ first 15 min those days│ marks on the chart   │ │
│  └────────────────────────┴────────────────────────┴──────────────────────┘ │
│                                                                             │
│  Warnings                                                                   │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ TIM gap  2025-06-12  17:00–17:04  CT                                   │ │
│  │ TIM gap  2025-06-18  17:00–17:02  CT                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Changelog (click ↔ chart)                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ ● CMP.*  2025-06-12  excluded 4 open slots                             │ │
│  │ ○ UNQ.*  2025-06-18  dropped 1 exact duplicate                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Daily OHLCV  [ clean ●  raw ghost  ]              Rolling 15-min VWAP      │
│  ┌─────────────────────────────────────────┐  ┌──────────────────────────┐  │
│  │     ▌▌  ●  ▌  ▌▌▌  ○  ▌                 │  │  ● ● ●    ● ●            │  │
│  │           ╎ghost close                  │  │       ╳ break            │  │
│  │ vol ▁▂▃▅▇▅▃▂▁▂▃▅                        │  │  (NULL where vol=0)      │  │
│  └─────────────────────────────────────────┘  └──────────────────────────┘  │
│  ● selected action   ○ other actions in window   ╳ VWAP undefined           │
│  if daily-only: VWAP panel stays, shows "needs minute bars" — not empty     │
│  no rule authoring · no findings log on the chart                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Analyst

Primary question: what is broken, and should we cleanse or keep it?

**Summary**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SUMMARY · analyst                                                           │
│                                                                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │
│  │ DQ score     │ │ Open findings│ │ Both freqs   │ │ Worst field        │  │
│  │ 64           │ │ 27           │ │ 3 contracts  │ │ close / timestamp  │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────────────┘  │
│                                                                             │
│  Loaded contracts · grouped by name · sorted by score then name             │
│  ┌────────┬─────────┬───────┬──────────┬──────────────────────────────────┐ │
│  │ Root   │ Contract│ Score │ Findings │ Top issue                        │ │
│  ├────────┼─────────┼───────┼──────────┼──────────────────────────────────┤ │
│  │ ZC     │ ZCZ25   │ 41    │ 9        │ VAL close outside range          │ │
│  │ CL     │ CLG26   │ 58    │ 6        │ REC daily vs minute volume       │ │
│  │ GC     │ GCG26   │ 61    │ 4        │ TIM timezone smear               │ │
│  │ SB     │ SBK26   │ 67    │ 3        │ VAL off-tick settlement          │ │
│  │ ES     │ ESZ25   │ 96    │ 1        │ CMP 4-slot open gap              │ │
│  └────────┴─────────┴───────┴──────────┴──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Specifics** — one contract, all issues; this is the deep view.

Click a findings-log row to open a **raw neighbourhood** of that finding:
offending rows highlighted, not editable. `VAL.close` is a daily row plus
neighbours; `CMP.gap` shows expected slots that are missing; `REC.vol` shows
both frequencies. Charts stay a separate check (“is this a market move?”).
Panel is collapsed until a finding is selected.

**v1 serves the neighbourhood at daily grain only.** `GET /v1/analytics/bars/daily`
on `basis=raw` over a window around the finding is the whole mechanism, which covers
`VAL.close` — the worked example above — and every other daily-grain finding. The
minute-grain cases are **not** served: `CMP.gap` needs the expected slot grid against
actual records and `REC.vol` needs both frequencies row by row, and no v1 route returns
raw market records. Those findings show their own evidence (the What column, from
`dq.dq_finding.details`) plus the charts, and the panel says which grain it is showing
rather than rendering empty. A raw-records route is the extension that lifts this; the
panel’s purpose — locate and explain, never edit — is met at daily grain today. Address is a suggested rule
as text (what / why / expected effect) — no apply. Findings and suggestions
are report-only this release.
Future: Override on the log; apply / dismiss on suggestions.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SPECIFICS · analyst                                                         │
│  Contract: ZCZ25 ▾           trade dates [2025-01-02 → 2025-12-19]          │
│  Score 41 · 9 findings · daily + minute loaded → REC.* in scope             │
│                                                                             │
│  Findings log (read-only)              selected: VAL.close  2025-12-12      │
│  ┌──────────┬────────────┬────────────────────────────────────┬──────────┐  │
│  │ Rule     │ When       │ What                               │ Severity │  │
│  ├──────────┼────────────┼────────────────────────────────────┼──────────┤  │
│  │ VAL.close│ 2025-12-12 │ close 412 > high 410               │ error    │  │
│  │ REC.vol  │ 2025-06-02 │ daily vol < minute sum             │ warn     │  │
│  │ CMP.gap  │ 2025-03-14 │ 18 missing minute slots            │ warn     │  │
│  │ OUT.mad  │ 2025-08-01 │ log-return spike (info)            │ info     │  │
│  └──────────┴────────────┴────────────────────────────────────┴──────────┘  │
│                                                                             │
│  Raw (neighbourhood of selected finding)                                    │
│  ┌────────────┬────────┬────────┬────────┬────────┬────────┬──────────────┐ │
│  │ ts_local   │ open   │ high   │ low    │ close  │ volume │ freq         │ │
│  │ 2025-12-11 │ 408.00 │ 411.25 │ 407.50 │ 410.00 │ 18210  │ daily        │ │
│  │ 2025-12-12 │ 410.25 │ 410.00 │ 407.00 │ 412.00 │ 20104  │ daily  ← bad │ │
│  │            │        │  ^^^^ close 412 > high 410                       │ │
│  │ 2025-12-13 │ 409.50 │ 412.00 │ 408.75 │ 411.25 │ 17602  │ daily        │ │
│  └────────────┴────────┴────────┴────────┴────────┴────────┴──────────────┘ │
│  not an editor · report-only · collapsed until a finding is selected        │
│                                                                             │
│  Patterns (lift)              Suggestions (report)           Changelog      │
│  ┌─────────────────────────┐  ┌───────────────────────────┐  ┌───────────┐  │
│  │ close fails  Mon  3.1×  │  │ Halt window for ZC        │  │ VAL.*     │  │
│  │ gaps hour  17:00  2.4×  │  │  Mon close fails; drop    │  │ excluded  │  │
│  │ REC only on daily file  │  │  those opens from clean   │  │ 2 closes  │  │
│  └─────────────────────────┘  └───────────────────────────┘  └───────────┘  │
│                                                                             │
│  Daily OHLCV (finding as overlay)    Minute vs daily / raw vs clean         │
│  ┌────────────────────────────────┐  ┌───────────────────────────────────┐  │
│  │ ▌▌  ▌  !  ▌▌▌                  │  │  supplied daily ──                │  │
│  │         ↑ flagged close        │  │  derived minute - - -             │  │
│  └────────────────────────────────┘  └───────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```
