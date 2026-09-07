# Plans

Committed execution sequence. Pointers only — design lives in `specs/`.

**Authority.** `specs/` is law. `_notes/` is a research scrapbook (gitignored). Plans are
sequence and done-when, not a second spec. If a spec and a note disagree, the spec wins.
See `.cursor/rules/docs-authority.mdc`.

**Promote first.** The first done-when of each slice is: promote the matching
`_notes/cursor/` research file into `specs/`. Empty stubs are worse than notes. Do not
implement solely from `_notes/`. Promoted so far: `specs/data-model.md` and
`specs/sample-corpus.md` (slice 1); `specs/dq-rules-and-scoring.md` (slice 2);
`specs/analytics-semantics.md` (slice 3 done-when 1); `specs/api-contract.md`
(slice 4 done-when 1). Slice 5 needed no promote — `specs/loupe-ui-design.md` was already
promoted from the founding notes — but it amended four specs: `api-contract.md` (§6.1, §6.5
and the v1 route table), `dq-rules-and-scoring.md` (§11.6, §11.7),
`loupe-ui-design.md` (Risk status and trend, the daily-grain neighbourhood) and
`loupe-solution-design.md` §13 (the UI test tier). Slice 9 rewrote the UI spec as one
reviewer page and added `GET /v1/dq/checks`.

Sequence matches `specs/loupe-solution-design.md` §17.

## Status

| # | Slice | Status | Plan |
|---|---|---|---|
| 1 | data ingest | **done** | [01-data-ingest.md](01-data-ingest.md) |
| 2 | quality | **done** | [02-quality.md](02-quality.md) |
| 3 | insights | **done** | [03-insights.md](03-insights.md) |
| 4 | api | **done** | [04-api.md](04-api.md) |
| 5 | ui | **done** | [05-ui.md](05-ui.md) |
| 6 | rec / suggestions / demo | **done** | [06-rec-suggestions-demo.md](06-rec-suggestions-demo.md) |
| 7 | demo corpus / first run | **done** | [07-demo-corpus.md](07-demo-corpus.md) |
| 8 | ingest chrome | **done** | [08-ingest-chrome.md](08-ingest-chrome.md) |
| 9 | reviewer-facing UI | **done** | [09-reviewer-ui.md](09-reviewer-ui.md) |
| 10 | reviewer chrome (click-test) | **done** | [10-reviewer-chrome.md](10-reviewer-chrome.md) |
| 11 | grain-honest review | pending | [11-grain-honest-review.md](11-grain-honest-review.md) |
| 12 | README walkthrough | pending | [12-readme-walkthrough.md](12-readme-walkthrough.md) |
| 13 | overview page | pending | [13-overview-page.md](13-overview-page.md) |

Slice 7 was split out of the walkthrough once it was clear the prose depends on it: there is
nothing to describe until the demo corpus, the CSV conversion and the two buttons exist. Slice 8
was split out again once the ingest path itself changed — dropping the uploader and listing
what loaded is chrome the walkthrough would otherwise describe wrongly. Slice 9 rebuilds the
main page around the brief’s four checks and two charts (no persona selector). Slice 10 is
chrome a click-test of 9 asked for (cards as the control, no score line, zoom + legend,
grouped sidebar). Slice 11 makes the selected quality grain explicit, aligns cards and
evidence with the plotted source, fixes Invalid and pattern pictures, and adds VWAP zoom.
Slice 12 then carries three findings from slice 6's integration tier and a limitations list
that is already decided, so it is assembly rather than discovery — and it must describe
the page after slice 11. Slice 13 adds an **Overview** sibling (corpus family-tile table)
without changing Review’s main column; it waits on 11 for honest grain rows. If 12 writes
after 13, name the Review / Overview switch; if 12 has already shipped, 13 patches it.

## Archive

Done slices stay in place; mark **done** here. Move a file to `plans/archive/` only when
it is **superseded**, not when it is finished.
