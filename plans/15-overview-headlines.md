# 15 — Overview family headlines only (follow-on to 14)

**Goal.** Overview family cells show only the card headline (`count unit`), not the
detail sentence. Glide does not honour a line break in `st.dataframe`, so the scan
is the number. Click-through, nav order, and default Review do not change.

**Status.** done — 2026-09-08

Written 2026-09-08, after a `/tmp` probe (`overview_headline_probe.py`, port 8511)
showed a six-column table of `5,209 runs` / `0 records` / `1 rows` / `74 standing`
is readable. The earlier newline probe (`overview_cell_probe.py`) showed `\n` and
`\n\n` do not render as two lines in this Streamlit/Glide build. Do not reopen 14.
Do not reopen 13. Amend the Overview table copy 14 wrote into the UI spec.

Page copy stays **Overview**, not Compare.

## Why this slice exists

Slice 14 capped column widths and put `count unit` on the first line of the cell
with detail after a newline. Glide still paints one run-on string, so pattern
sentences shove the scan. The headline alone is what the four Review cards lead
with. Detail stays on Review (card body, picture, issues).

## Spec updates (required — done-when 1)

Amend in place. One-line revision at the top of each touched spec. No `*-v2.md`.

| Spec | What to rewrite |
|---|---|
| `specs/loupe-ui-design.md` | Overview table: family cells are `count unit` only (e.g. `5,209 runs`). Drop “two lines / wrapping detail”. Unchecked remains “Check has not run”. Column `help` on the family headers is unchanged. |
| `specs/loupe-solution-design.md` | §12 Overview sentence: headlines, not tile detail. §17: this slice after 14. Do not rewrite locked decision 6. Do not change default landing. |

Do **not** touch analytics, DQ, sample-corpus, API routes, or `data-model.md`. No new
route. The checks envelope still returns `detail`; the widget does not print it.
`docs/how-loupe-works.md` only if it would still teach Overview cells as count +
detail.

## Settle in the UI spec, not in widgets

1. **Headline only.** `family_cell` returns `{count:,} {unit}` (and the existing
   unchecked / error strings). Do not concatenate `detail`. Do not use
   MarkdownColumn, `\n`, or custom HTML to fake a second line.
2. **Review unchanged.** Cards still show count and detail. Overview is the cull
   surface, not a second card strip.
3. **Chrome 14 stays.** Overview left of Review; default Review; column widths;
   Contract bold; `st.dataframe` row click.
4. **Help.** Family meaning stays on the column header `help` (already
   `helptext.CARDS`). Do not invent per-cell tooltips.

## Implementation shape

`src/loupe/ui/overview.py` — `family_cell`. Tests that assert a newline and a
detail sentence. No `quality` import, no bulk checks route.

## Done when

1. UI spec and solution §12 / §17 agree: Overview family cells are headlines only.
2. Table cells match `N unit` (thousands separators as today); no session-open /
   exact-copy / standing-pattern prose in the grid.
3. Unchecked still says “Check has not run”. Click-through, grain filter, nav
   order, and default Review still pass.

## Tests

`tests/ui/test_overview.py`: `family_cell` is `2 runs` not
`2 runs\n1 session-open hole · …`; table still has the four family headers.
No new API or DQ tests.

## Files

- `specs/loupe-ui-design.md` (Overview table)
- `specs/loupe-solution-design.md` §12, §17
- `src/loupe/ui/overview.py`
- `tests/ui/test_overview.py`
- `plans/README.md`

## Non-goals

- Making Glide wrap or honour `\n`.
- Default landing Overview (still Review unless a later slice says otherwise).
- Putting `detail` in a hover. Canvas row tones, noise sort, dual-grain subtitle.
- Review card copy, overlay grammar, date window, score column.

## Attach

- `specs/loupe-ui-design.md` (Overview)
- [14-overview-table.md](14-overview-table.md)
- Probe (not law, not in git): `/tmp/overview_headline_probe.py`
