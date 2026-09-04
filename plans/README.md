# Plans

Committed execution sequence. Pointers only — design lives in `specs/`.

**Authority.** `specs/` is law. `_notes/` is a research scrapbook (gitignored). Plans are
sequence and done-when, not a second spec. If a spec and a note disagree, the spec wins.
See `.cursor/rules/docs-authority.mdc`.

**Promote first.** The first done-when of each slice is: promote the matching
`_notes/cursor/` research file into `specs/`. Empty stubs are worse than notes. Do not
implement solely from `_notes/`. Promoted so far: `specs/data-model.md` and
`specs/sample-corpus.md` (slice 1); `specs/dq-rules-and-scoring.md` (slice 2).

Sequence matches `specs/loupe-solution-design.md` §17.

## Status

| # | Slice | Status | Plan |
|---|---|---|---|
| 1 | data ingest | **done** | [01-data-ingest.md](01-data-ingest.md) |
| 2 | quality | pending | [02-quality.md](02-quality.md) |
| 3 | insights | pending | [03-insights.md](03-insights.md) |
| 4 | api | pending | [04-api.md](04-api.md) |
| 5 | ui | pending | [05-ui.md](05-ui.md) |
| 6 | rec / suggestions / demo | pending | [06-rec-suggestions-demo.md](06-rec-suggestions-demo.md) |
| 7 | README walkthrough | pending | this index (no slice file) |

Slice 7: walkthrough in the delivered README against real `ESZ25` (or a chosen volatile
window). Philosophy, architecture, trade-offs, limitations, extensibility — see solution
brief §16.

## Archive

Done slices stay in place; mark **done** here. Move a file to `plans/archive/` only when
it is **superseded**, not when it is finished.
