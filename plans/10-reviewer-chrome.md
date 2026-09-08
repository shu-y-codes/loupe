# 10 — Reviewer chrome (click-test)

**Goal.** Spec, then ship, the chrome a click-test of slice 9 asked for: cards *are* the
family control, help on the count, no score line on the page, zoomable OHLCV + volume, a
chart legend, and a grouped sidebar (ingested files by grain; planted defects by family).

**Status.** done — 2026-09-08 (follow-on click-test polish)

Written 2026-09-07, after a demo-load click-test of [09-reviewer-ui.md](09-reviewer-ui.md).
09 stays **done**. Do not reopen it except the pointer in that file. Do not reopen
[05-ui.md](05-ui.md) or [08-ingest-chrome.md](08-ingest-chrome.md). Amend the specs they
pointed at.

[11-grain-honest-review.md](11-grain-honest-review.md) follows this slice.
[12-readme-walkthrough.md](12-readme-walkthrough.md) stays pending and must describe the
page after 11, not the score caption or the extra Check control.

## The change

Slice 9 shipped the right page shape (four named checks, two charts, picture below VWAP)
and the wrong chrome around it:

- Family titles live twice: a `Check` segmented control *and* four metric cards.
- Help hangs on the card title, not on `42 runs`.
- A score caption under the cards (`Score 98.6842 · cmp+… · load the minute tape…`)
  competes with the four checks the brief asked for.
- Chart marks are explained in a caption, not a legend. Daily OHLCV and volume do not zoom.
- Ingested files are a flat list. After injection, planted rows are a flat rule table.

Keep overlay grammar, `GET /v1/dq/checks`, picture-below-VWAP, aggregated issues, Load demo
data / Inject, report-only. This slice is chrome and grouping, not a second reviewer UI.

## Filename

Amend **`specs/loupe-ui-design.md` in place.** No `*-v2.md`. One-line revision at the top.
Solution brief §12 stays the pointer + invariants; it must not keep “score as a caption”
as a second truth.

## Settle in the UI spec (done-when 1), not in widgets

1. **Cards are the selector.** The four cells are the family control. No separate row of
   Check buttons / segmented control. Selected state lives on the card. Help moves from
   the title to the **count** (`42 runs`). Family names stay as labels without `?`.
2. **No score line on this page.** Drop the caption that renders `score`,
   `scope_signature`, and the missing-grain / reconciliation sentence. The four cards
   lead; aggregated issues stay. `GET /v1/dq/checks` may still return those fields — the
   page stops drawing them.
3. **Missing-grain copy (close this).** The score caption is today the only main-column
   home for “settlement judged on the daily file alone — load the minute tape.” Daily-only
   VWAP already says “needs minute bars.” Pick one: drop the reconciliation sentence
   (VWAP refusal is enough) **or** give it a new non-score home. Do not leave it only on
   the API envelope, and do not keep a score-shaped caption to carry it.
4. **OHLCV legend, not caption.** Marks, bands, and lines for the **selected family** are
   a chart legend (pin / dashed absent / paint / volume / pattern band). Rule IDs stay off
   the candle; they may still caption the picture. Overlay grammar does not change.
5. **Zoom.** Daily OHLCV **and** the volume pane pan/zoom (shared x). How to reset is
   named. VWAP and the picture ribbon are out of this note unless the spec adds them.
6. **Ingested files, grouped by coverage.** Not by the file’s own frequency alone:
   **daily + minute**, **daily-only**, **minute-only**. A contract with both grains lists
   both files under the first bucket. Use `GET /v1/ingest/batches` + `GET /v1/contracts`
   (already sidebar HTTP). No new route unless the spec finds the client would have to
   guess from filenames. CSV-from-Parquet mark unchanged.
7. **Synthetic disclosure, grouped by strip family.** Injection is **one** planted file
   with many labelled defects (`loupe.demo.injection` manifest, keyed by `rule_id`). Group
   those rows under Gaps / Duplicates / Invalid values using the same catalogue family map
   as the cards. Nest the filename under each family that appears. Recurring patterns are
   insights, not planted rows — no synthetic bucket. **Off-strip** planted rules
   (`TIM.OUT_OF_ORDER`, and anything else injection can plant that is not on the strip)
   get a named other/off-strip group, not a silent drop and not a fifth card.

## Backend

None expected. Do not add a route so Streamlit can avoid grouping two inventory lists it
already fetches. Do not change rule triggers, scores, cleaning, or overlay payloads.

`scope_signature` remains required **when a score is displayed**
(`specs/dq-rules-and-scoring.md` §11.3). This page stops displaying one.

## Done when

### Spec — first

1. **`specs/loupe-ui-design.md`** — tooltips, product-questions table, wireframe, main-column
   order, family cards, delete Score caption section (or replace with the missing-grain
   decision from settle #3), Daily OHLCV legend + zoom, sidebar ingested-file grouping,
   synthetic grouping. Help attach list: count/unit, not card title; drop score-caption
   jargon if the line is gone.

2. **`specs/loupe-solution-design.md` agrees.** §2 trust line: cards + issues, not score
   caption. §12 invariants: cards *are* the selector; no score caption; legend; zoom;
   grouped sidebar. §16 UI checkbox. §17 inserts this slice; README walkthrough becomes
   11 and describes the page **after** this chrome.

3. **Sibling specs — grep, do not second-spec the UI.** Pointers only where a sentence
   still teaches a score caption on the reviewer page (`specs/api-contract.md` §6.6
   example is an envelope, not a widget). `specs/dq-rules-and-scoring.md` §11.3 stays
   about displaying a score, not about this page.

   **Do not edit** `_notes/founding/`. Do not reopen 09's overlay grammar or family map.

### Then code

4. **`ui`:** cards select family (no `Check` control); help on the count; no score
   caption; Altair (or current chart) zoom on OHLCV + volume with shared x; legend;
   sidebar groups; synthetic expander groups by family. Thin widgets; HTTP only.

5. **Tests.** `AppTest`: no segmented `Check` control; no caption starting `Score `;
   clicking a card (not a second control) still changes overlay / picture family;
   ingested-file expander names the three coverage groups when stubbed batches mix
   grains; after a stubbed injection, planted rows are grouped under strip family
   labels, with off-strip present if the stub includes `TIM.*`. Zoom is hard to assert
   in AppTest — spec + a chart helper test that the spec is enough unless a unit is
   cheap.

## Sequencing

Done-when 1–3 (specs) before any widget. 4 and 5 together. Do not start
[12-readme-walkthrough.md](12-readme-walkthrough.md) before slice 11.

## Files

- `specs/loupe-ui-design.md` — chrome rewrite of the sections above.
- `specs/loupe-solution-design.md` — §2, §12, §16, §17.
- `src/loupe/ui/review.py` — drop `_family_control`; cards are the control; drop score
  caption.
- `src/loupe/ui/help.py` — help on counts; drop unused score jargon if the spec drops it.
- `src/loupe/ui/charts.py` — legend; pan/zoom on candles + volume.
- `src/loupe/ui/demo.py` — ingested-file groups; synthetic manifest groups.
- `src/loupe/ui/runtime.py` — `checks_score_caption` goes if nothing else calls it.
- `tests/ui/` — AppTest cases in done-when 5.

## Attach

- [09-reviewer-ui.md](09-reviewer-ui.md) — done; overlay grammar and `/v1/dq/checks` stay
- `specs/loupe-ui-design.md` (Sidebar, Tooltips, Family cards, Score caption, Daily OHLCV)
- `specs/loupe-solution-design.md` §2, §12, §17
- `specs/dq-rules-and-scoring.md` §11.3 (display rule, not a page widget)
- `src/loupe/quality/catalogue.py` — family map (read; do not relitigate)
- `src/loupe/demo/injection.py` — `INJECTABLE_RULES` / manifest shape
- [08-ingest-chrome.md](08-ingest-chrome.md) — done; list exists; this slice groups it
- [11-grain-honest-review.md](11-grain-honest-review.md) — next UI correctness slice
- [12-readme-walkthrough.md](12-readme-walkthrough.md) — blocked on 11

## Non-goals

New rules, score formula, overlay payloads, apply/override, auth, file uploader, zoom on
VWAP or the picture ribbon, a fifth family card, implementing from `_notes/`, starting the
README walkthrough against the score caption.

---

## Follow-on — click-test polish (done — 2026-09-08)

Notes from a browser pass of the shipped chrome (`_notes/dev/markups.txt`; scrapbook only
until promoted). Tiny UI polish. No new route, no overlay payload change, no score formula.

**Spec change: yes, light — `specs/loupe-ui-design.md` only.** Demo lessons that change
product copy or chart chrome patch the UI spec the same day
(`.cursor/rules/docs-authority.mdc`). Do **not** touch solution brief §2/§12 unless a
sentence would still teach the wrong sidebar disclosure. No API / DQ / analytics spec.

Promote into the UI spec before widgets:

| Note | Spec touch | Why |
|---|---|---|
| Count slightly larger than body; detail line at regular size | Family cards: type hierarchy (count leads; detail is body) | KPI chrome |
| OHLCV hover: date, open, high, low, close, status (`clean` or defect type) | Daily OHLCV / Tooltips: marker and candle hover fields; status from selected-family marks | Tooltip law |
| Absent: annotate on the chart (canvas-style label), not only a colour swatch in the legend | Daily OHLCV already says “dashed column **labelled** absent” — make the on-chart label explicit; legend may keep a colour entry | Overlay chrome; Vega legends do not show stroke-dash well |
| Volume hover must not show raw `fill` | Volume pane: tooltip is date + volume (+ defect if any), not the colour field name | Tooltip law |
| Sidebar synthetic warning: drop “findings below were planted”; list planted file(s) grouped by strip family | Synthetic disclosure: the **sidebar** warning carries the grouped list (reuse the same family map / filename nest); main-column expander may stay or thin | Product copy |

### Done when (follow-on)

1. **`specs/loupe-ui-design.md`** — one-line revision; Family cards type hierarchy; OHLCV
   hover + on-chart absent label; volume tooltip; sidebar synthetic warning wording. **done**
2. **`ui`:** card typography; Altair tooltips + absent `mark_text` (or equivalent);
   volume tooltip without `fill`; sidebar warning lists planted file under Gaps /
   Duplicates / Invalid / Other (off the strip). Reuse `group_planted_by_family`. **done**
3. **Tests.** Chart helper: status tooltip fields / absent label present in the Vega
   spec; volume tooltip excludes `fill`. AppTest or demo helper: sidebar synthetic copy
   does not say “findings below”; grouped family labels appear when a stubbed manifest
   is present. **done**

Follow-on landed 2026-09-08. Next:
[11-grain-honest-review.md](11-grain-honest-review.md), then
[12-readme-walkthrough.md](12-readme-walkthrough.md).