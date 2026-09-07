# Loupe UI design

Revised 2026-09-07: one reviewer page — four family cards, Daily OHLCV then 15-minute VWAP
with selected-family overlays, picture of the selected family below VWAP. No persona
selector. Sidebar ingest is still **Load demo data**; after a load the sidebar lists
ingested batches and marks demo CSVs converted from Parquet.

## UI philosophy

The page names the brief’s four checks and two charts. Cards answer *what is wrong, of
which kind*. Charts answer *what it looks like*, keyed on the selected check. The picture
under VWAP is the close look at that same family.

It provides **report-only** evidence. Findings and suggestions are identified, not applied.

## Tooltips

Help on **named boxes** (family cards, KPI-style tiles, column headers), not on every grid
cell. One sentence, in this page’s language — not a persona dialect. Streamlit:
`st.metric(..., help=...)`, dataframe column `help`, chart caption. Not a glossary overlay.

**Attach help**

- Family cards: Gaps, Duplicates, Invalid values, Recurring patterns
- Score caption jargon: `scope_signature`, “needs minute bars”
- Column headers on the aggregated issues table: What, Days, Records, What we did
- Marked sessions (how many dates the selected family flags)

Examples: Gaps — “Missing timestamps and absent sessions — holes in the expected grid, not
a quiet market.” Recurring patterns — “Standing concentrations, corrected for how often
that bucket appears in the records.” What we did — “What default cleaning did, from the
changelog. This page does not apply a new rule.”

**Skip**

- Aggregated-issue What cells and picture sentences — those *are* the explanation
- Candle bodies once the selected-family marks are labelled on the chart
- Rule IDs or expected-effect JSON in a hover. Rule IDs are a **caption**, never the
  headline

## Product questions

The page answers the two questions in `specs/loupe-solution-design.md` §1, for **one
selected contract** and the sidebar date window:

| Question | What the page shows |
|---|---|
| Can I trust this data? | Four check cards (zero means the check ran), a score **caption** with `scope_signature`, aggregated issues (What / Days / Records / What we did) |
| What does this data look like? | Daily OHLCV then rolling 15-minute VWAP, marks for the **selected family** only, picture of that family below VWAP |

Filter by **contract and date**. There is no book-grain inventory and no persona view
selector. A book strip is an extension.

**v1 does not override findings or apply suggestions from the UI.** Address lives in
What we did (changelog) and in picture copy. No apply, override, dismiss, or edit control.

## Overlay grammar

Key candles on the **selected family**, not `max_severity`. `max_severity` stays on the
bar envelope for the publish gate (`specs/analytics-semantics.md` §3.3). This page does
not paint with it.

| Family | Daily OHLCV | 15-min VWAP |
|---|---|---|
| Gaps | Pin / triangle on session-open holes; dashed column if the settlement never arrived. Never a zero-filled bar. | Named break where window volume was dropped. |
| Duplicates | Pin on the kept timestamp. Do not recolor the body. | Usually none. |
| Invalid values | Paint that candle; volume pane for volume defects. | Only if cleaning dropped the window. |
| Recurring patterns | Band every participating session. | Shade the concentrating hour. |

`OUT.*` stays off this strip (optional in the brief). Captions under the charts **explain
the marks**; they do not argue a proposal.

Family → rule map (engine unchanged; labelling + grouping). Catalogue home is the same as
`SETTLEMENT_RULES`: `src/loupe/quality/catalogue.py`. HTTP envelope:
`GET /v1/dq/checks` (`specs/api-contract.md` §6.6).

| Card | Counts toward it | Do not mix in |
|---|---|---|
| Gaps | `CMP.MISSING_TIMESTAMP`, `CMP.SESSION_MISSING`, `CMP.PARTIAL_SESSION` | `CMP.NULL_FIELD` (invalid *value*) |
| Duplicates | `UNQ.EXACT_DUPLICATE`, `UNQ.KEY_CONFLICT` | Duplicate *files* (ingest list) |
| Invalid values | `VAL.*` plus `CON.HIGH_LT_LOW` / open-or-close outside range, and `CMP.NULL_FIELD` | `OUT.*` |
| Recurring patterns | `GET /v1/insights/patterns` narratives | A count of findings as the lead |

A rule is in exactly one of the three strip families or in **off-strip** (`OUT.*` and
everything the table leaves off). Recurring patterns is not a rule family; its card count
is standing patterns in the window, not finding count.

**Minute gaps on a daily chart.** A minute `CMP.MISSING_TIMESTAMP` must be able to mark
the **derived daily** session when Daily OHLCV is on screen. Frequency-aware
`max_severity` intersection is the wrong overlay key.

**Absent settlements.** Expected grid vs `mart.bar_daily`, never a zero-filled bar
(`CMP.SESSION_MISSING` — `specs/analytics-semantics.md` §3.4). The overlay row exists;
the bar row does not.

Widgets do not group `findings[]` to build cards or overlay marks. Those envelopes are
composed in `quality`.

## Sidebar

Trade dates, contract picker, and demo ingest. There is **no file uploader** and **no
persona radio**.

**Contract.** One selected contract for the four cards, both charts, the picture, and the
issues table. The picker lists loaded contracts (`GET /v1/contracts`). An empty store has
no picker.

**Load demo data** is the only v1 UI ingest path. Locked decision 9 already named the
button; it is chrome here, not only a sentence in the solution brief. It posts files
already on local disk to `POST /v1/ingest/batches` with `origin=demo`
(`specs/api-contract.md` §4.3). Arbitrary CSV or Parquet ingest remains an API path. The
UI is not a second way to do the same thing.

**Ingested files** appear after a successful load. The list is `GET /v1/ingest/batches`
— filename, format, origin — inventory of what the store holds, not a second ingest
control and not a walk of `data/samples/`. Converted rows show as CSV; the Parquet they
replaced is not in the load (`specs/sample-corpus.md` §8).

**CSV mark.** Rows with `origin = demo` and CSV (`file_format` or suffix) are marked
**converted from Parquet**, so a reviewer can see the CSV half of "accept CSV or
Parquet" without opening a directory. That copy is a format fact, not a defect. After
injection the planted file is also a CSV; that mark is the synthetic disclosure
(`origin = injected`), not this one. Do not key the conversion mark off "any CSV".

**Empty store.** The main column says no contracts are loaded and points at Load demo
data. A failed fetch is answered in place and does not point at an uploader.

**Capability preview is not on this page.** `POST /v1/ingest/preview` stays as an API
dry run. Demo load skips per-file preview (`validate=False`, then one corpus-wide run).
Unavailable capabilities are disclosed in place on the dashboard after load — VWAP keeps
its panel and says "needs minute bars"; a daily-only score caption names the missing
minute tape. There is no pre-commit sidebar matrix.

## Wireframe

```
┌──────────────────┬──────────────────────────────────────────────────────────┐
│ LOUPE            │  ESZ25 · 2025-06-02 → 2025-06-30                         │
│                  │                                                          │
│ Contract         │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────────────┐  │
│  [ESZ25     ▾]   │  │ Gaps    │ │Duplicates│ │ Invalid │ │ Recurring     │  │
│                  │  │ 42 runs │ │ 4 records│ │ 12 rows │ │ 2 standing    │  │
│ Trade dates      │  │ 18 holes│ │ 3 exact  │ │ 8 prices│ │ Open-hour     │  │
│  [2025-01-02]    │  │ 2 absent│ │ 1 conflict│ │ 4 vols  │ │ gaps, 61/63   │  │
│  [2025-12-19]    │  └─────────┘ └─────────┘ └─────────┘ └────────────────┘  │
│                  │  Score 96 · cmp+val+con+unq+tim · load minute tape to    │
│ Demo data        │  reconcile. Zero on a card means the check ran.          │
│ Inject defects   │                                                          │
│                  │  Daily OHLCV · clean series · selected family            │
│ Ingested files   │  ┌────────────────────────────────────────────────────┐  │
│  ESZ25.parquet   │  │  ▲ ▲    ▲     ╎absent╎     ▲          paint        │  │
│  parquet · demo  │  │ vol ▁▂▃▅▇▅▃▂▁                                      │  │
│  SR3G26.csv      │  └────────────────────────────────────────────────────┘  │
│  csv · demo      │  Triangles: session-open holes. Dashed: settlement never │
│  from Parquet    │  arrived. Rule IDs in the caption, not on the candle.    │
│                  │                                                          │
│                  │  Rolling 15-minute VWAP                                  │
│                  │  ┌────────────────────────────────────────────────────┐  │
│                  │  │  ╳ ╳  ● ● ● ●    ● ●                               │  │
│                  │  └────────────────────────────────────────────────────┘  │
│                  │  Crosses name the break. Daily-only: panel stays,        │
│                  │  "needs minute bars".                                    │
│                  │                                                          │
│                  │  Picture of gaps                                         │
│                  │  ┌─┬─┬─┬─┬─┬─┬─┬─┬─┬─┐  17:00 CT open: four slots     │
│                  │  │■│■│■│■│□│□│□│□│□│□│  missing. CMP.MISSING_TIMESTAMP │
│                  │  └─┴─┴─┴─┴─┴─┴─┴─┴─┴─┘                                  │
│                  │                                                          │
│                  │  Issues in this window                                   │
│                  │  ┌────────────────┬──────┬─────────┬──────────────────┐  │
│                  │  │ What           │ Days │ Records │ What we did      │  │
│                  │  │ Session-open   │ 18   │ 72      │ excluded 4 open  │  │
│                  │  │ holes          │      │         │ slots            │  │
│                  │  └────────────────┴──────┴─────────┴──────────────────┘  │
└──────────────────┴──────────────────────────────────────────────────────────┘
```

## Main column

Order is load-bearing: **cards, score caption, Daily OHLCV, VWAP, picture, aggregated
issues.** Expanding the picture must not shove the charts. Both charts are **full width**.

HTTP: `GET /v1/dq/checks` for cards, score, overlay marks, picture payload, and issues;
`GET /v1/analytics/bars/daily` for OHLCV; `GET /v1/analytics/vwap` for the line. The page
joins overlay marks to bars **by `trade_date`**. It does not group `findings[]`.

### Family cards

Four cards. Selecting a card selects the overlay, the chart captions, and the picture.
Zero is a real answer: the check ran and found nothing in this contract × window.

The selected card is visually distinct. Rule IDs do not headline the card; they may appear
in a caption on the picture or under the chart.

### Score caption

The four cards lead. Score is a **caption under the cards**, not a competing headline
tile. `scope_signature` still travels with it (`specs/dq-rules-and-scoring.md` §11.3).
Equal signature means comparable; unequal means the page must say so. When reconciliation
is out of scope, name the missing companion grain and the consequence (settlement judged
on the daily file alone — load the minute tape to reconcile it). Do not mark a book of
scores against each other: there is no inventory column.

Below `params.min_records`, show "insufficient data" instead of a number. Never render
absent as zero.

### Daily OHLCV

The **clean** series. Overlay marks from `checks.overlay.ohlcv` for the selected family:

- **Gaps, present bar, partial hole:** triangle / pin on the candle. The body stays the
  clean series — the defect is missing time, not a bad close.
- **Gaps, absent settlement:** dashed column labelled absent. No OHLC. Never a
  zero-filled candle.
- **Duplicates:** pin on the kept timestamp. Do not recolor the body.
- **Invalid values:** paint that candle. Volume defects sit on the volume pane.
- **Patterns:** shaded band on every participating session, including absences that
  belong to the pattern.

`max_severity` may still arrive on the bar envelope; ignore it for colour. A holiday with
no finding is not an absent settlement.

Caption explains the marks on screen. Rule IDs may follow in smaller type.

### Rolling 15-minute VWAP

Null windows are a **break**, not a connected line (`specs/analytics-semantics.md`).
When the selected family is Gaps or Recurring patterns, name the break (cross / gap
mark) where window volume was dropped. Patterns additionally shade the concentrating
hour. Duplicates usually leave the line alone. Invalid values mark a break only if
cleaning dropped the window.

**Daily-only keeps the panel** and says "needs minute bars" — the structured
`CAP.FREQUENCY_UNAVAILABLE` refusal, not an empty chart and not a 15-day VWAP.

### Picture of the selected family

Same family as the cards and overlay. Lives **below VWAP**.

| Family | Picture |
|---|---|
| Gaps | Ribbon of expected minute slots around the hole (present vs missing). An absent settlement is a sentence: the column never arrived; Loupe did not invent a bar. Draw the ribbon with a Vega chart, not SVG via `st.html`. |
| Duplicates | Two-row table: kept vs dropped, same timestamp. |
| Invalid values | The broken bar, with the impossible cell obvious (close above high, negative volume, …). |
| Recurring patterns | The pattern sentence plus a histogram of share-of-findings vs share-of-records. |

When the family is empty (check ran, count is zero): the picture says so. Do not render
an empty ribbon that looks like a full session.

### Aggregated issues

One row per *(family, plain-language issue)* in the window — not one row per finding and
not Why-as-code (`OUT.RETURN_MAD · date`).

| Column | Source |
|---|---|
| What | `dq.dq_rule.name` (or the pattern narrative) |
| Days | Distinct `trade_date`s |
| Records | `affected_rows` / changelog `records` as the envelope decided |
| What we did | Changelog labels. The widget does not re-derive cleaning. |

No corroboration second-line in this table. No apply column. Help on headers; none on
What / What we did cells.

## Empty, daily-only, and no-finding states

| State | What the page does |
|---|---|
| No contracts loaded | Main column points at Load demo data. No empty charts pretending to be a clean bill. |
| Contract loaded, no completed run | Cards and charts wait; say that validation has not finished. |
| Check ran, count is zero | Card shows **0**. Picture: this check found nothing in the window. |
| Daily-only | VWAP panel stays with "needs minute bars". Score caption names the missing minute tape when reconciliation is out of scope. |
| Minute-only | Daily OHLCV is derived from the tape. Absent *settlements* still come from the daily expected grid vs `mart.bar_daily`; a minute-only contract has no vendor settlement row to miss. |
| API down | Error in place. Do not invite an uploader. |

## Report-only

No apply, override, dismiss, accept, resolve, or edit control anywhere in the tree.
Suggestions that exist on `GET /v1/insights/suggestions` are not a second table on this
page; What we did is the changelog. Apply / dismiss remain extensions.
