# 13 — Overview page (corpus family tiles)

**Goal.** Add a second Streamlit page that lists loaded contracts against the four family
tiles, so a reviewer can cull the demo set. **Review’s main column does not change.**

**Status.** done — 2026-09-08

Follow-on chrome (fit, wrap, Overview left of Review): [14-overview-table.md](14-overview-table.md).
Do not reopen this file for that work.

Written 2026-09-08, after a live-store scan of 40 contracts × grain. Keep
[09-reviewer-ui.md](09-reviewer-ui.md), [10-reviewer-chrome.md](10-reviewer-chrome.md),
and 11 **done or pending as they are**. Do not reopen them. Do not reopen
[05-ui.md](05-ui.md). Amend the specs they pointed at.

[12-readme-walkthrough.md](12-readme-walkthrough.md) remains the README walkthrough and
stays blocked on 11, not on this slice. Implement Overview after 11 even if 12 has not
started. If 12 writes after this, name the Review / Overview switch. If 12 has already
shipped, this slice patches the walkthrough with one navigation paragraph.

Page copy is **Overview**, not Compare: `GET /v1/analytics/compare` already owns that
word (raw vs clean, daily vs derived).

## Why this slice exists

Demo day needs a **smaller, high-noise** contract list. Today the picker is 40 symbols
and the only way to scan family cards is to click each contract. The table is already
computable from `GET /v1/contracts` + `GET /v1/dq/checks` (no new route). Putting that
table on Review would shove the charts. A sibling page keeps Review intact.

## Spec updates (required — done-when 1)

This is **v1**, not an extension. Several specs still teach “one reviewer page,” which
was the anti-persona lock (slice 9), not a ban on a second functional destination.

Amend in place. One-line revision at the top of each touched spec. No `*-v2.md`.

| Spec | What to rewrite |
|---|---|
| `specs/loupe-ui-design.md` | **Home of the page.** Navigation, Overview sidebar vs Review sidebar, Overview main column (table + optional root chart), click-through, empty store. Add an Overview wireframe. Add the Review / Overview switch to the **existing** Review wireframe; do not otherwise change Review’s main-column order. |
| `specs/loupe-solution-design.md` | Locked decision **6**: keep “No authentication”; replace “one reviewer page, not a view selector” with two pages that are still not persona-shaped. §2 table stays the Review answers; add Overview as the corpus scan. §12: “Two pages,” Review invariants unchanged, Overview pointer to the UI spec. §13 UI tier: two-page assembly, still no persona switch. §15: Overview data flow (loop checks, no `findings[]` grouping). §16 checkbox: Review **plus** Overview. §17: this slice before the README walkthrough. |
| `specs/api-contract.md` §8 | Same sentence: still no auth and not persona-aware; drop “one reviewer page” or replace with two pages. **No new routes.** |
| `specs/data-model.md` §6 | `user` / `role` row: still no auth; UI is not a role view selector. |

**Do not touch** `analytics-semantics.md`, `dq-rules-and-scoring.md`, or
`sample-corpus.md`. Overview reads the checks envelope slice 11 already owns.

`docs/how-loupe-works.md` is not a spec. Patch only if a sentence would still teach a
single-page app; otherwise leave it for 12.

## Settle in the UI spec, not in widgets

1. **Two destinations, sidebar only.** Segmented control under the Loupe title:
   **Review** | **Overview**. Default **Review** so the existing walkthrough still lands
   on cards and charts. Not a persona radio, not a main-column tab, not a third page.
2. **Review is unchanged below the switch.** Contract, Quality grain, trade dates,
   Load demo data, inject, ingested files, four cards, both charts, picture, issues —
   same order, same HTTP. The only Review chrome this slice adds is the nav control.
3. **Overview is a corpus scan, not a second Review.** Rows = loaded contract × held
   grain (dual-grain contracts appear twice). Headers = the four family tiles (count,
   unit, detail), plus Grain. Full held window (empty date pickers). No contract picker,
   no Quality grain control, no From / To on this page.
4. **Shared ingest.** Load demo data, inject, and the ingested-file list stay on both
   pages so Overview is reachable on an empty store without bouncing back.
5. **Click-through.** Selecting an Overview row opens Review with that `contract` and
   `quality_grain` already set. Family stays whatever Review last had (default gaps).
6. **No new API.** Compose in `ui` by calling the existing client (`contracts()`, then
   `checks(contract=, frequency=)` per row). Cache the table for the store’s current
   batches/run so a rerun does not fire 40× checks. Do not group `findings[]` in the
   widget. Do not add a bulk `/dq/checks` route unless the loop is shown to be too
   slow for demo (measure; don’t invent).
7. **Empty / unchecked.** No contracts → same invitation to Load demo data as Review.
   `checked: false` → say the check has not run, do not fake zeros as “clean.”

Page copy: **Review** and **Overview**. Do not revive Risk / Trader / Analyst.

## Implementation shape

Streamlit `st.navigation` (or equivalent) with two pages. Shared chrome: title, nav,
demo panel. Review-only chrome stays in `chrome.py` as it is. Overview is a new module
under `src/loupe/ui/` that takes checks envelopes and draws the table — HTTP in the
page, no SQL, no `quality` import. Do not name that module `compare.py`
(`insights/compare.py` already exists).

`app.py` remains the Review entry so existing `AppTest` paths keep pointing at it.
The navigation wrapper is the new run target; page tests that today `AppTest` Review
must still pass without visiting Overview.

## Done when

1. Specs in the table above agree: two pages, Review invariants intact, Overview
   behaviour listed, locked decision 6 rewritten, no second truth in §12.
2. Nav: Review | Overview in the sidebar; default Review; Overview does not render
   Review’s cards/charts.
3. Overview table: one row per contract × held grain; four family columns match
   `GET /v1/dq/checks` `families[]` for that contract × frequency on the full window.
4. Click a row → Review shows that contract and grain.
5. Load demo data / inject / file list work from Overview. Empty store copy points at
   Load demo data.
6. Existing Review `AppTest` suite stays green with the nav present. New tests cover
   Overview assembly, grain-filter if shipped, click-through session keys, and that
   Review still has exactly four family cards and no score line.
7. Browser-pass: land on Review, switch to Overview, open `ESZ25` minute, confirm
   Review cards/charts. Dual-grain row count matches `frequencies_available`.

## Tests

`tests/ui/` over the stubbed client. Stub `checks` per contract/frequency (reuse
`ui_helpers` envelope keys; stub-parity against the model still applies). Assert:

- Review path: four cards, no score caption, charts still assemble (existing tests).
- Overview path: headers Gaps / Duplicates / Invalid values / Recurring patterns;
  a dual-grain fixture yields two rows; a daily-only fixture yields one.
- Click-through writes `contract` and `quality_grain`.
- Overview does not call `bars_daily` / `vwap` to draw the table.

No new API tests. No DQ formula tests.

## Files

- `specs/loupe-ui-design.md`
- `specs/loupe-solution-design.md` §2, §3.6, §12, §13, §15, §16, §17
- `specs/api-contract.md` §8
- `specs/data-model.md` §6
- `src/loupe/ui/` — navigation wrapper, Overview module, shared demo chrome; `chrome.py`
  / `review.py` / `charts.py` only if the nav cannot sit above them without a touch
- `tests/ui/test_pages.py` (Review still), new Overview page tests
- `plans/README.md` (index); [12-readme-walkthrough.md](12-readme-walkthrough.md) if
  the walkthrough would otherwise omit the switch

## Non-goals

- Culling the demo corpus itself (no change to `data/demo/`, fetch list, or inject).
- A bulk checks route, score column, or book-grain inventory.
- Date window on Overview, persona views, apply/override.
- Changing overlay grammar, family-card copy, or Review chart order.
- Rewriting `docs/how-loupe-works.md` beyond a one-line nav fact if it is already wrong.

## Attach

- `specs/loupe-ui-design.md` (Review law to keep; Overview to add)
- `specs/loupe-solution-design.md` §2, §3.6, §12
- `specs/api-contract.md` §6.6 (`families[]` shape), §8
- [11-grain-honest-review.md](11-grain-honest-review.md) — frequency on checks
- [12-readme-walkthrough.md](12-readme-walkthrough.md)
