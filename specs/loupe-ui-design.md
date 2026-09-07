# Loupe UI design

Revised 2026-09-08: grain-honest review — explicit Quality grain, source-aligned evidence,
selected-family issues, pattern exposure chart, independent VWAP zoom and scope-keyed chart
identity. Earlier the same day: click-test polish — card count/detail type hierarchy; OHLCV hover
(date, OHLC, status); on-chart **absent** label; volume tooltip without colour-field
noise; sidebar synthetic warning lists planted file(s) by strip family. Same day prior:
reviewer chrome — cards *are* the family control (no Check row), no score line, OHLCV
legend + shared-x zoom, ingested files grouped by contract coverage, planted defects
grouped by strip family. Same day: one reviewer page — four family cards, Daily OHLCV
then 15-minute VWAP with selected-family overlays, picture of the selected family below
VWAP. No persona selector. Sidebar ingest is still **Load demo data**.

## UI philosophy

The page names the brief’s four checks and two charts. Cards answer *what is wrong, of
which kind*. Charts answer *what it looks like*, keyed on the selected check. The picture
under VWAP is the close look at that same family.

It provides **report-only** evidence. Findings and suggestions are identified, not applied.

## Tooltips

Help on **named boxes** (family-card **counts**, KPI-style tiles, column headers), not on
every grid cell. One sentence, in this page’s language — not a persona dialect. Streamlit:
help on the count line, dataframe column `help`. Overlay marks are a chart legend, not a
hover glossary.

**Chart hover** (Daily OHLCV and markers): date, open, high, low, close, and **status**
(`clean`, or a plain defect type such as `gap: session-open hole` / `gap: session missing`
/ `duplicate` / `invalid value` / `volume defect` / `pattern member`). Status comes from
the selected-family overlay marks, not `max_severity`. Volume pane hover: date, volume,
and status when relevant — never the raw colour encoding field name (`fill`).

**Attach help**

- Family-card **count / unit** (`42 runs`, `4 records`) — not the family name
- Column headers on the aggregated issues table: What, Days, Records, What we did
- VWAP panel: “needs minute bars” stays on the refused daily-only panel

Examples: Gaps count — “Missing timestamps and absent sessions — holes in the expected
grid, not a quiet market.” Recurring patterns count — “Standing concentrations, corrected
for how often that bucket appears in the records.” What we did — “What default cleaning
did, from the changelog. This page does not apply a new rule.”

**Skip**

- Aggregated-issue What cells and picture sentences — those *are* the explanation
- Glossary sentences on candle bodies (the legend + status hover cover that)
- Rule IDs or expected-effect JSON in a hover. Rule IDs are a **caption**, never the
  headline

## Product questions

The page answers the two questions in `specs/loupe-solution-design.md` §1, for **one
selected contract** and the sidebar date window:

| Question | What the page shows |
|---|---|
| Can I trust this data? | Four check cards (zero means the check ran). The cards *are* the family selector. Aggregated issues (What / Days / Records / What we did). No score line on this page. |
| What does this data look like? | Daily OHLCV then rolling 15-minute VWAP, marks for the **selected family** only (legend on OHLCV), picture of that family below VWAP |

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

`OUT.*` stays off this strip (optional in the brief). OHLCV **legend** names the selected
family’s marks; it does not argue a proposal. Rule IDs stay off the candle.

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

Trade dates, contract picker, Quality grain, and demo ingest. There is **no file uploader** and **no
persona radio**.

**Contract.** One selected contract for the four cards, both charts, the picture, and the
issues table. The picker lists loaded contracts (`GET /v1/contracts`). An empty store has
no picker.

**Quality grain.** A contract holding both `minute` and `daily` shows a two-option
**Quality grain** segmented control and defaults to **Minute**. The current selection persists
when the contract changes if that grain is available; otherwise it resolves to Minute when
available, then Daily. A single-grain contract has no choice control and instead shows the held
grain as quiet context. The page header and OHLCV subtitle always name the resolved grain.
Cards, patterns, selected-family issues, picture, overlays and OHLCV all use that grain:
Minute reads derived daily bars from the minute tape; Daily reads supplied vendor daily bars.
Changing family never changes grain.

**Load demo data** is the only v1 UI ingest path. Locked decision 9 already named the
button; it is chrome here, not only a sentence in the solution brief. It posts files
already on local disk to `POST /v1/ingest/batches` with `origin=demo`
(`specs/api-contract.md` §4.3). Arbitrary CSV or Parquet ingest remains an API path. The
UI is not a second way to do the same thing.

**Ingested files** appear after a successful load. The list is `GET /v1/ingest/batches`
plus `GET /v1/contracts` (already sidebar HTTP) — filename, format, origin — inventory of
what the store holds, not a second ingest control and not a walk of `data/samples/`.
Converted rows show as CSV; the Parquet they replaced is not in the load
(`specs/sample-corpus.md` §8).

**Group by contract coverage, not by the file’s own frequency.** Three buckets: **Daily +
minute**, **Daily-only**, **Minute-only**. A contract that holds both grains lists **both**
of its files under Daily + minute — the daily file of a dual-grain contract does not sit
in Daily-only. Coverage comes from `frequencies_available` on the contract, filled from
batch `frequency` when that list is empty. No new route. CSV-from-Parquet mark unchanged.

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
its panel and says "needs minute bars". The page does not draw a score caption to name the
missing minute tape. There is no pre-commit sidebar matrix.

## Wireframe

```
┌──────────────────┬──────────────────────────────────────────────────────────┐
│ LOUPE            │  ESZ25 · 2025-06-02 → 2025-06-30                         │
│                  │                                                          │
│ Contract         │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────────────┐  │
│  [ESZ25     ▾]   │  │ Selected│ │Duplicates│ │ Invalid │ │ Recurring     │  │
│                  │  │ Gaps    │ │          │ │ values  │ │ patterns      │  │
│                  │  │ 42 runs │ │ 4 records│ │ 12 rows │ │ 2 standing    │  │
│ Trade dates      │  │ 18 holes│ │ 3 exact  │ │ 8 prices│ │ Open-hour     │  │
│  [2025-01-02]    │  │ 2 absent│ │ 1 conflict│ │ 4 vols  │ │ gaps, 61/63   │  │
│  [2025-12-19]    │  └─────────┘ └─────────┘ └─────────┘ └────────────────┘  │
│                  │  Cards are the selector. Help on 42 runs, not Gaps.      │
│ Demo data        │                                                          │
│ Inject defects   │  Daily OHLCV · clean series · selected family            │
│                  │  ┌────────────────────────────────────────────────────┐  │
│ Ingested files   │  │  ▲ ▲    ▲     ╎absent╎     ▲          paint        │  │
│  Daily + minute  │  │ vol ▁▂▃▅▇▅▃▂▁                                      │  │
│   ESZ25.parquet  │  └────────────────────────────────────────────────────┘  │
│   ESZ25.csv      │  Legend: ▲ hole · ╎ absent. Drag dates to pan/zoom;     │
│  Minute-only     │  double-click to reset. Rule IDs off the candle.        │
│   SR3G26.csv     │                                                          │
│   from Parquet   │                                                          │
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

Order is load-bearing: **cards, Daily OHLCV, VWAP, picture, aggregated issues.** Expanding
the picture must not shove the charts. Both charts are **full width**. There is **no
score line** under the cards.

HTTP: `GET /v1/dq/checks` for cards, overlay marks, picture payload, and issues;
`GET /v1/analytics/bars/daily` for OHLCV; `GET /v1/analytics/vwap` for the line. The page
joins overlay marks to bars **by `trade_date`**. It does not group `findings[]`. The
page passes Quality grain explicitly to checks and daily bars. The envelope may still include
`score` / `scope_signature`; this page does not draw them.

### Family cards

Four cards. **The cards are the family control** — no separate Check segmented control or
second button row. Clicking a card selects the overlay, the OHLCV legend, and the picture.
Selected state lives on the card. Family names are labels without `?`. Help attaches to
the **count** (`42 runs`), not the title.

**Type hierarchy.** The count / unit line leads and is **slightly larger** than body text.
The detail line under it (e.g. `0 exact copies · 0 key conflicts`) is **regular** body
size — not a competing KPI number.

Zero is a real answer: the check ran and found nothing in this contract × window. Rule IDs
do not headline the card; they may appear in a caption on the picture.

### Missing grain

Drop the score line entirely, including `scope_signature` and the reconciliation sentence
(“settlement judged on the daily file alone”). Do not invent a new score-shaped caption to
carry those words. Daily-only VWAP already says “needs minute bars”
(`CAP.FREQUENCY_UNAVAILABLE`) — that is the page’s missing-grain copy. When a score *is*
displayed on some other surface, `specs/dq-rules-and-scoring.md` §11.3 still applies.

### Daily OHLCV

The **clean** series. Overlay marks from `checks.overlay.ohlcv` for the selected family:

- **Gaps, present bar, partial hole:** triangle / pin on the candle. The body stays the
  clean series — the defect is missing time, not a bad close.
- **Gaps, absent settlement:** dashed column with an on-chart **absent** label (canvas-style
  annotation). No OHLC. Never a zero-filled candle. The legend may keep a colour entry for
  “Settlement never arrived”; Vega legends do not show stroke-dash well, so the on-chart
  label is the readable mark.
- **Duplicates:** pin on the kept timestamp. Do not recolor the body.
- **Invalid values:** paint that candle. Volume defects sit on the volume pane.
- **Patterns:** shaded band on every participating session, including absences that
  belong to the pattern.

`max_severity` may still arrive on the bar envelope; ignore it for colour. A holiday with
no finding is not an absent settlement.

**Legend, not caption.** Pin / triangle, dashed absent, paint, volume-pane defect, and
pattern band for the **selected family** are a chart legend. Overlay grammar does not
change. Rule IDs stay off the candle; they may still caption the picture.

**Hover.** Candles and overlay markers show date, open, high, low, close, and status
(see Tooltips). Absent columns have no OHLC; their hover/status is the session-missing
defect type.

**Source.** The subtitle says **Derived from minute** at minute Quality grain and
**Supplied daily** at daily Quality grain.

**Zoom and identity.** Daily OHLCV **and** the volume pane pan and zoom together on a
**shared x** (trade date). Drag to pan or zoom the dates; **double-click to reset**. Initial
render fits the returned extent. Contract, Quality grain, or From / To changes create a new
chart identity and reset to that filtered extent; a family-only change keeps the same identity
and preserves zoom. Explicit date filters remain authoritative across contract changes.

### Rolling 15-minute VWAP

Null windows are a **break**, not a connected line (`specs/analytics-semantics.md`).
When the selected family is Gaps or Recurring patterns, name the break (cross / gap
mark) where window volume was dropped. Patterns additionally shade the concentrating
hour. Duplicates usually leave the line alone. Invalid values mark a break only if
cleaning dropped the window.

**Daily-only keeps the panel** and says "needs minute bars" — the structured
`CAP.FREQUENCY_UNAVAILABLE` refusal, not an empty chart and not a 15-day VWAP.

VWAP has its own scale-bound x selection: drag to pan or zoom and double-click to reset.
Its chart identity changes with contract or From / To, but not family. When Quality grain is
Daily and the contract also holds minute records, keep the line and label it
**Minute tape · context only for Daily quality grain**; suppress daily selected-family marks.
At Minute quality grain the selected-family marks return.

### Picture of the selected family

Same family as the cards and overlay. Lives **below VWAP**.

| Family | Picture |
|---|---|
| Gaps | Ribbon of expected minute slots around the hole (present vs missing). An absent settlement is a sentence: the column never arrived; Loupe did not invent a bar. Draw the ribbon with a Vega chart, not SVG via `st.html`. |
| Duplicates | Two-row table: kept vs dropped, same timestamp. |
| Invalid values | The accused stage record or source-aligned bar, naming the actual subject field and evidence grain/source. A volume rule never falls back to `close`. |
| Recurring patterns | One focused `(rule_id, dimension)` group: sentence, rule ID and chart all refer to it. Say **Showing 1 of N standing patterns** (or how many related buckets are shown). The x title is the plain dimension; y is **Share (%)**; paired series are **Findings** and **Records (exposure)**; each bucket carries a lift label. Hover includes bucket, both shares, lift, support and distinct days. Explain that over-representation is findings share above record exposure and that the standing threshold, not count alone, admits a pattern. |

When the family is empty (check ran, count is zero): the picture says so. Do not render
an empty ribbon that looks like a full session.

### Aggregated issues

Heading: **Issues in selected family** (the label may be included). One row per
*(selected family, plain-language issue)* in the window — not one row per finding and
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
| Daily-only | VWAP panel stays with "needs minute bars". No score caption and no extra reconciliation sentence. |
| Minute-only | Daily OHLCV is derived from the tape. Absent *settlements* still come from the daily expected grid vs `mart.bar_daily`; a minute-only contract has no vendor settlement row to miss. |
| API down | Error in place. Do not invite an uploader. |

## Report-only

No apply, override, dismiss, accept, resolve, or edit control anywhere in the tree.
Suggestions that exist on `GET /v1/insights/suggestions` are not a second table on this
page; What we did is the changelog. Apply / dismiss remain extensions.

## Synthetic disclosure

Injection is **one** planted file with many labelled defects (`loupe.demo.injection`
manifest, keyed by `rule_id`). Group those rows under **Gaps**, **Duplicates**, and
**Invalid values** using the same catalogue family map as the cards
(`src/loupe/quality/catalogue.py` `strip_family`). Nest the planted **filename** under
each family that appears. Recurring patterns are insights, not planted rows — no synthetic
bucket for that card.

**Off-strip** planted rules (`TIM.OUT_OF_ORDER`, and anything else injection can plant that
is not on the strip) get a named group **Other (off the strip)** — not dropped, not a
fifth card.

**Sidebar warning.** When synthetic batches are loaded, the sidebar says how many synthetic
records are loaded and lists the planted **file(s) grouped by strip family** (same map /
filename nest as above). Do **not** say “findings below were planted” — nothing follows
that sentence in the sidebar. The main-column expander may still show the full planted
table for evidence.
