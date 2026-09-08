# 12 — README walkthrough

**Goal.** The delivered README a reviewer reads first: philosophy, architecture, trade-offs,
limitations, extensibility, and a walkthrough against real `ESZ25` (solution brief §16).

**Status.** pending — blocked on [11-grain-honest-review.md](11-grain-honest-review.md)

Written 2026-09-07, after slice 6 shipped and after the integration tier went in; renumbered
from 07 when the demo-corpus work was split out ahead of it, then from 08 when ingest chrome
was inserted ahead of that, then to 10 so the reviewer-facing UI could ship as slice 9, then
to 11 so click-test chrome could ship as slice 10, then to 12 so the grain-honest review
could ship as slice 11.

Slice 9 replaced the persona Summary / Specifics page; slice 10 is the chrome a click-test
asked for; slice 11 aligns cards, evidence and charts on an explicit frequency and clarifies
the pattern picture. This walkthrough describes **that** page, so it runs after 11, not in
parallel. [13-overview-page.md](13-overview-page.md) adds an Overview sibling. If 13 has
shipped when this is written, name the Review / Overview switch; do not wait on 13 to
describe Review. [14-overview-table.md](14-overview-table.md) puts Overview to the left
of Review; [16-overview-default.md](16-overview-default.md) makes Overview the default
landing. Name the shipped order and landing behaviour.
[15-overview-headlines.md](15-overview-headlines.md) keeps Overview family cells as
`count unit` only; name that if 15 has shipped.

**Slices 7–11 are hard dependencies, not a nicety.** The walkthrough is prose *about* a
corpus, a sidebar, and the main page. Until [07-demo-corpus.md](07-demo-corpus.md) there is
no CSV file to name or demo button to describe. Until
[08-ingest-chrome.md](08-ingest-chrome.md) the sidebar does not show what was loaded. Until
[09-reviewer-ui.md](09-reviewer-ui.md) the main column is still persona Summary / Specifics.
Until [10-reviewer-chrome.md](10-reviewer-chrome.md) the page still has a score caption and
a second Check control. Until [11-grain-honest-review.md](11-grain-honest-review.md), a
card can count supplied-daily findings while the chart silently draws the minute-derived
series, and the pattern picture can caption one pattern while charting another. Write this
after all five, not alongside them.

## Done when

1. **The walkthrough runs from a clone with no setup step.** `bootstrap` seeds the schema,
   reference data and rule catalogue. The documented path is two commands, one click,
   findings on real vendor data, and loaded files visible (CSV conversions marked; coverage
   groups from slice 10). Verify by hand on a fresh clone with an empty `data/`. Anything
   needing a Python REPL before the app works is a bug, not a step to document.
2. **Philosophy, architecture and trade-offs**, in reviewer reading order rather than build
   order. Locked decisions (`specs/loupe-solution-design.md` §3) are the spine: say what was
   chosen, rejected, and what the choice costs.
3. **Limitations, stated rather than implied.** Use the established list below.
4. **The walkthrough itself, on real data**, against `ESZ25` or a chosen volatile window:
   fetch, ingest both grains, re-run corpus-wide, select Quality grain, select a family card,
   see the same-grain overlay and picture, zoom OHLCV and VWAP, and read one standing
   pattern with exposure share and lift. Real numbers only; no screenshot code cannot
   reproduce. Do not teach the removed score caption.
5. **Extensibility**: what a new rule, vendor profile and venue cost, and which named
   extensions (§14) were left out — suggestion apply, finding override, AI narratives,
   async ingest.
6. **Endpoint-to-requirement table** from `specs/api-contract.md` §9, including insights.

## Carried in from slice 6

**A batch-scoped run does not put reconciliation in scope.** `POST /v1/ingest/batches`
runs rules over that batch. After the second grain lands, a corpus-wide
`POST /v1/dq/runs` is required. Load demo data already does this. It remains an API
limitation, not a file-uploader journey.

**The score is absent, not zero, below `min_records`.** A small scope scores `None` with
`insufficient_data` (§11.5). The reviewer page no longer shows a score, so this is an API /
limitations statement, not a click.

**Reconciliation close is noisier per session than the sample median suggests.** On the
real ES corpus, over 67 coverage-gated sessions, open/high/low agree exactly, but 18 sessions
produce `REC.OHLC_DISAGREE` on close because settlement landed nearer the last trade than
the 15:00 print. This is per-root configuration and only ES is measured
(`specs/sample-corpus.md` §6.3).

## Limitations already established

- **Daily-only keeps VWAP's panel** and says “needs minute bars”
  (`CAP.FREQUENCY_UNAVAILABLE`).
- **Mixed scope is normal.** A displayed score must carry `scope_signature`; this page
  does not display one. Slice 11 makes the selected quality frequency explicit.
- **Two pattern dimensions are not computed.** `field` and `rule` lack an exposure
  denominator; lift is undefined for them.
- **Three suggestion generators are absent** because they require per-finding field
  attribution not grouped from `dq.dq_finding.details`.
- **Settlement mark is seeded for CME default only.** A root whose session never reaches
  it gets no close comparison, under-reporting rather than accusing.
- **Suggestions are report-only.** Apply, dismiss and override remain extensions.
- **`ApiProblem` is a frozen dataclass subclassing `RuntimeError`.** It works but is fragile;
  pytest has surfaced `FrozenInstanceError` while formatting one.

## Files

Edited: `README.md` — the whole document.

Nothing in `src/` should need to change for the prose. If it does, that is a finding:
the README is claiming something the app cannot do.

## Tests

No new tier. Existing tests cover cold start, ingest/reconciliation, OpenAPI traceability,
sidebar inventory, card selection, grain-honest evidence and chart interactions.

This slice owes a **manual pass on a clean clone**: clone, `uv sync`, run the two commands,
click Load demo data, and follow the walkthrough exactly. Fix prose where reality disagrees.

## Attach

- `specs/loupe-solution-design.md` §3, §14, §16
- `specs/api-contract.md` §9
- `specs/dq-rules-and-scoring.md` §11.5
- `specs/sample-corpus.md` §1
- [08-ingest-chrome.md](08-ingest-chrome.md)
- [09-reviewer-ui.md](09-reviewer-ui.md)
- [10-reviewer-chrome.md](10-reviewer-chrome.md)
- [11-grain-honest-review.md](11-grain-honest-review.md)
- [13-overview-page.md](13-overview-page.md) — name the switch if that slice has shipped

## Non-goals

New features. If the walkthrough wants a capability that does not exist, the answer is a
sentence in Limitations, unless it exposes a defect in something already claimed to work.
