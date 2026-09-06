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
`loupe-solution-design.md` §13 (the UI test tier).

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
| 8 | README walkthrough | pending | [08-readme-walkthrough.md](08-readme-walkthrough.md) |

Slice 7 was split out of the walkthrough once it was clear the prose depends on it: there is
nothing to describe until the demo corpus, the CSV conversion and the two buttons exist. Slice 8
then carries three findings from slice 6's integration tier and a limitations list that is
already decided, so it is assembly rather than discovery.

## Archive

Done slices stay in place; mark **done** here. Move a file to `plans/archive/` only when
it is **superseded**, not when it is finished.
