# 10 — README walkthrough

**Goal.** The delivered README a reviewer reads first: philosophy, architecture, trade-offs,
limitations, extensibility, and a walkthrough against real `ESZ25` (solution brief §16).

**Status.** pending — blocked on [09-reviewer-ui.md](09-reviewer-ui.md)

Written 2026-09-07, after slice 6 shipped and after the integration tier went in; renumbered
from 07 when the demo-corpus work was split out ahead of it, then from 08 when ingest chrome
was inserted ahead of that, then to 10 so the reviewer-facing UI could ship as slice 9.
Slice 9 replaced the persona Summary / Specifics page; this walkthrough describes **that**
page, so it runs after 9, not in parallel.

**Slices 7, 8 and 9 are hard dependencies, not a nicety.** The walkthrough is prose *about* a
corpus, a sidebar, and the main page. Until [07-demo-corpus.md](07-demo-corpus.md) there is no
CSV file to name, no demo button to describe, and no answer to "what does a reviewer see first".
Until [08-ingest-chrome.md](08-ingest-chrome.md) that sidebar still offers Upload files and does
not show what was loaded. Until [09-reviewer-ui.md](09-reviewer-ui.md) the main column is still
persona Summary / Specifics, which is not what the walkthrough should teach. Write this after
all three, not alongside them.

## Done when

1. **The walkthrough runs from a clone with no setup step.** `bootstrap` seeds the schema,
   reference data and the rule catalogue, and `loupe.api.app:bootstrapped_app` is the
   zero-argument factory `uvicorn --factory` needs. Slice 7 adds the demo-data button and
   slice 8 is the sidebar around it, so the documented path is: two commands, one click,
   findings on real vendor data, the loaded files visible (CSV conversions marked). Verify
   by hand on a fresh clone with an empty `data/`. Anything that needs a Python REPL before
   the app works is a bug, not a step to document.
2. **Philosophy, architecture and trade-offs**, in the reviewer's reading order rather than the
   build order. The locked decisions (`specs/loupe-solution-design.md` §3) are the spine: say
   what was chosen, what was rejected, and what the choice costs. A trade-off with no cost
   named is a feature list.
3. **Limitations, stated rather than implied.** The list is known and each has a spec reference,
   so this is assembly rather than discovery — see "Limitations already established" below.
4. **The walkthrough itself, on real data**, against `ESZ25` or a chosen volatile window: fetch,
   ingest both grains, re-run corpus-wide, read the score caption, select a family card and
   see the overlay and picture, read one standing pattern. Real numbers, and no screenshot
   that the code cannot reproduce.
5. **Extensibility**: what a new rule, a new vendor profile and a new venue each cost, and which
   named extensions (§14) were deliberately left out — suggestion apply, finding override, AI
   narratives, async ingest.
6. **The endpoint-to-requirement table** of `specs/api-contract.md` §9, kept in the delivered
   README as that section asks. It is the traceability a reviewer checks the brief against, and
   it now includes the two insights routes.

## Carried in from slice 6

Three findings from the integration tier that this slice has to say out loud rather than
leaving for the reviewer to hit.

**A batch-scoped run does not put reconciliation in scope.**
`POST /v1/ingest/batches` runs the rules scoped to *that batch*, so when a second grain lands
the run has never seen the other records. It takes a corpus-wide `POST /v1/dq/runs`. This is
pinned by `tests/integration/test_walkthrough.py`. Slice 8 removes the upload widget, and Load
demo data already finishes with that corpus-wide run, so a reviewer following the click path
never hits this. It remains true of the API. The walkthrough should not teach a file_uploader
path; name it as an API limitation if it is named at all.

**The score is absent, not zero, below `min_records`.** A small demo file scores `None` with
`insufficient_data` set (§11.5). The walkthrough should either use enough data to score or show
the insufficient-data state deliberately, because a reviewer seeing an em dash where they
expected a number will read it as a bug.

**Reconciliation's close branch is noisier per session than §6.3's median suggests.** On the
real ES corpus, over 67 coverage-gated sessions: zero `open`/`high`/`low` disagreements — the
§8.1 invariant holds exactly — but 18 sessions produce a `REC.OHLC_DISAGREE` **error** on
`close` because that settlement landed nearer the last trade than the 15:00 print. This is what
§8.4 specifies, and it is worth a sentence in the limitations rather than a surprise: the mark
is per-root configuration and only ES is measured (`specs/sample-corpus.md` §6.3).

## Limitations already established

Each of these is decided and referenced; the slice writes them up, it does not reopen them.

- **Daily-only hides VWAP, not the panel.** The VWAP panel stays and says "needs minute bars"
  (`CAP.FREQUENCY_UNAVAILABLE`). Settlement still lives in the daily file; a minute-only
  contract has no vendor settlement row to miss (`specs/analytics-semantics.md` §3.4).
- **Mixed scope is the default, not an edge case.** 32 of 40 contracts score over five
  dimensions and 8 over six, so the score caption must carry `scope_signature` (§11.3).
- **Two pattern dimensions are not computed.** `field` and `rule` have no exposure denominator,
  so lift is undefined for them; the off-tick case is reachable through `frequency` instead
  (`src/loupe/quality/patterns.py`).
- **Three suggestion generators are absent** for the same reason — they need per-finding field
  attribution, and `dq.dq_finding.details` is evidence that is never grouped on
  (`specs/data-model.md` §4).
- **The settlement mark is seeded for the CME default only.** A root whose session never reaches
  it gets no close comparison at all, which under-reports rather than accuses (§8.4).
- **Suggestions are report-only.** Apply, dismiss and finding override are extensions (§14),
  and their absence is asserted rather than assumed.
- **`ApiProblem` is a frozen dataclass subclassing `RuntimeError`.** It works, and it is
  fragile: pytest surfaced a `FrozenInstanceError` while formatting one. Worth a line in
  known-issues, or ten minutes to unfreeze it.

## Files

Edited: `README.md` — the whole document.

Nothing in `src/` should need to change for the prose. If it does, that is a finding rather
than a chore: the README describing something the app cannot do is the defect this slice exists
to catch.

## Tests

No new tier. The claims the README makes are already covered — the two-command start by
`tests/integration/test_cold_start.py`, the ingest round trip and the reconciled book by
`tests/integration/test_walkthrough.py`, the endpoint table by `tests/api/test_openapi.py`,
the sidebar list and CSV mark by slice 8's UI tests.

What this slice owes is a **manual pass on a clean clone**: `git clone`, `uv sync`, run the two
commands, click Load demo data, follow the walkthrough as written, and fix the README where
reality disagrees. Do it on a machine that has never run Loupe, or the one thing being tested —
that a stranger can start it — is the one thing not being tested.

## Attach

- `specs/loupe-solution-design.md` §3 (locked decisions), §14 (extensibility and non-goals),
  §16 (deliverables checklist)
- `specs/api-contract.md` §9 (the endpoint-to-requirement table this README must carry)
- `specs/dq-rules-and-scoring.md` §11.5 (the score is a navigation tool, not a grade)
- `specs/sample-corpus.md` §1 (why the corpus is fetched and never committed)
- [08-ingest-chrome.md](08-ingest-chrome.md) (the sidebar the walkthrough screenshots)

## Non-goals

New features. If the walkthrough wants a capability that does not exist, the answer is a
sentence in Limitations, not a slice 8 implementation. The one exception is a defect the
walkthrough surfaces in something already claimed to work — that gets fixed, because the
README is the claim.
