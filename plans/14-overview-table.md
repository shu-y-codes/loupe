# 14 — Overview table chrome (follow-on to 13)

**Goal.** Make the Overview family-tile table readable in one viewport width, and put
**Overview** to the left of **Review** in the sidebar switch. **Default landing stays
Review.** Click-through and the checks loop do not change.

**Status.** pending — blocked on [13-overview-page.md](13-overview-page.md) (done).

Written 2026-09-08, after a live Overview pass: Glide sizes family columns to the
longest pattern sentence, so the table scrolls horizontally. A canvas table
(`contract-family-tiles.canvas.tsx`) showed why that hurts: contract id and `count unit`
should read as headlines; detail wraps underneath. Do not reopen 13. Do not reopen
11 or 12. Amend the specs 13 already owns.

Page copy stays **Overview**, not Compare.

## Why this slice exists

Slice 13 shipped the destination and the HTTP. The table is the cull surface and it
currently fails as a scan: six columns overflow, detail sits on one long line, and
the nav reads Review | Overview (landing page first, not scan-first). Those are chrome
bugs on an existing page, not a third destination.

## Spec updates (required — done-when 1)

Amend in place. One-line revision at the top of each touched spec. No `*-v2.md`.

| Spec | What to rewrite |
|---|---|
| `specs/loupe-ui-design.md` | Navigation: **Overview \| Review** (Overview left), default still **Review**. Overview main column: table fits the main-column width (no horizontal scroll); family cells are two lines (headline `count unit`, then wrapping detail); Contract is visually heavier than detail. Update both wireframes’ `[Review\|Overview]` to `[Overview\|Review]`. |
| `specs/loupe-solution-design.md` | §12 nav sentence: Overview left of Review, default Review. §17: this slice after 13. Do not rewrite locked decision 6. |

Do **not** touch analytics, DQ, sample-corpus, API routes, or `data-model.md`. No new
route. `docs/how-loupe-works.md` only if it still teaches Review \| Overview order.

[12-readme-walkthrough.md](12-readme-walkthrough.md) names the switch when it writes;
if 12 has already shipped, patch one sentence for Overview-left.

## Settle in the UI spec, not in widgets

1. **Nav order.** Segmented control: **Overview** then **Review**. Default **Review**
   so existing `AppTest.from_file(app.py)` still lands on cards and charts. Not a
   persona radio. Not a change to which page is home.
2. **Fit.** All six columns visible in the main column without horizontal scroll.
   Vertical scroll for many rows is fine. Stay on `st.dataframe` so row click still
   opens Review.
3. **Wrap.** Family cells keep `count unit` on the first line and detail on following
   wrapped lines (already a newline in `family_cell`). Cap column widths so Glide
   wraps instead of expanding. Unchecked copy (“Check has not run”) is unchanged.
4. **Headline weight.** Contract id is bold (or equivalent heavier weight). Family
   headline is the first line (`count unit`); Streamlit cannot mix fonts inside one
   Glide cell — do not fake it with MarkdownColumn (raw source in the cell) or custom
   HTML. Pandas Styler on the Contract column is in bounds if it survives `st.dataframe`.
5. **Click-through unchanged.** Selecting a row still queues Review with that contract
   and Quality grain. Family stays whatever Review last had.

## Implementation shape

`src/loupe/ui/chrome.py` — `PAGES` order. `src/loupe/ui/overview.py` — `column_config`
widths (and Styler if Contract bold needs it). Tests that hard-code Review \| Overview
option order. No `quality` import, no `compare.py`, no bulk checks route.

## Done when

1. UI spec and solution §12 / §17 agree: Overview left of Review, default Review,
   table fits and wraps, Contract heavier than detail.
2. Sidebar switch shows Overview then Review; a cold load is still Review (four
   family cards, charts).
3. Overview table: no horizontal scroll at the app’s wide layout; family detail
   wraps under the headline; Contract reads heavier than the detail lines.
4. Click-through, grain filter, empty-store invitation, and “Check has not run”
   still pass. Existing Review `AppTest` suite stays green.

## Tests

`tests/ui/test_overview.py` and `test_pages.py`: nav options order Overview then
Review; default value Review; table still has the four family headers and one row
per held grain; click-through session keys unchanged. No new API or DQ tests.

## Files

- `specs/loupe-ui-design.md` (nav + Overview table + both wireframes)
- `specs/loupe-solution-design.md` §12, §17
- `src/loupe/ui/chrome.py`, `src/loupe/ui/overview.py`
- `tests/ui/test_overview.py`, `tests/ui/test_pages.py`
- `plans/README.md`; [12-readme-walkthrough.md](12-readme-walkthrough.md) if it would
  teach Review \| Overview order

## Non-goals

- Canvas extras: row-tone stripes, noise-first sort, dual-grain subtitle, root bar
  chart, KPI row.
- Custom HTML / CCv2, `st.table` (drops `on_select`), MarkdownColumn overlay.
- Date window, score column, bulk checks route, Review main-column changes.
- Culling `data/demo/`.

## Attach

- `specs/loupe-ui-design.md` (Overview table + Navigation)
- [13-overview-page.md](13-overview-page.md)
- Canvas reference only (not law): `canvases/contract-family-tiles.canvas.tsx`
  (`ContractCell` / `TileCell` weight — replicate the *read*, not the React)
