# 08 — README walkthrough

**Goal.** The delivered README a reviewer reads first: philosophy, architecture, trade-offs,
limitations, extensibility, and a walkthrough against real `ESZ25` (solution brief §16).

**Status.** pending

Written 2026-09-07, after slice 6 shipped and after the integration tier went in; renumbered
from 07 when the demo-corpus work was split out ahead of it. Slices 1-6 each left the README a
paragraph; this slice makes it the document the work is judged by. Three things are already
known and should not be rediscovered — see "Carried in from slice 6".

**Slice 7 is a hard dependency, not a nicety.** The walkthrough is prose *about* a corpus, and
until [07-demo-corpus.md](07-demo-corpus.md) lands there is no CSV file to name, no demo button
to describe, and no answer to "what does a reviewer see first". Write this after that, not
alongside it.

## Done when

1. **The walkthrough runs from a clone with no setup step.** `bootstrap` seeds the schema,
   reference data and the rule catalogue, and `loupe.api.app:bootstrapped_app` is the
   zero-argument factory `uvicorn --factory` needs. Slice 7 adds the demo-data button, so the
   documented path is: two commands, one click, findings on real vendor data. Verify by hand on
   a fresh clone with an empty `data/`. Anything that needs a Python REPL before the app works
   is a bug, not a step to document.
2. **Philosophy, architecture and trade-offs**, in the reviewer's reading order rather than the
   build order. The locked decisions (`specs/loupe-solution-design.md` §3) are the spine: say
   what was chosen, what was rejected, and what the choice costs. A trade-off with no cost
   named is a feature list.
3. **Limitations, stated rather than implied.** The list is known and each has a spec reference,
   so this is assembly rather than discovery — see "Limitations already established" below.
4. **The walkthrough itself, on real data**, against `ESZ25` or a chosen volatile window: fetch,
   ingest both grains, re-run corpus-wide, read the score, open one finding and its
   corroboration, read one pattern and one suggestion. Real numbers, and no screenshot that the
   code cannot reproduce.
5. **Extensibility**: what a new rule, a new vendor profile and a new venue each cost, and which
   named extensions (§14) were deliberately left out — suggestion apply, finding override, AI
   narratives, async ingest.
6. **The endpoint-to-requirement table** of `specs/api-contract.md` §9, kept in the delivered
   README as that section asks. It is the traceability a reviewer checks the brief against, and
   it now includes the two insights routes.

## Carried in from slice 6

Three findings from the integration tier that this slice has to say out loud rather than
leaving for the reviewer to hit.

**Uploading a second grain does not put reconciliation in scope.**
`POST /v1/ingest/batches` runs the rules scoped to *that batch*, so when the daily file lands
the run has never seen the minute records. It takes a corpus-wide `POST /v1/dq/runs`. This is
pinned by `tests/integration/test_walkthrough.py` and it will bite a reviewer who uploads two
files and expects the score to move. Either the walkthrough names the re-run as a step, or the
UI nudges after a second grain arrives — the second is better and is a small change to the
upload flow, so decide which before writing the prose around it.

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

- **Risk metrics depend on daily files.** Closing-day callouts and the settlement trend are
  daily-grain by design (§11.6); a minute-only corpus loses two of Risk's five columns and one
  of its four tiles, and the screen says so.
- **Mixed scope is the default, not an edge case.** 32 of 40 contracts score over five
  dimensions and 8 over six, so the `†` mark and the scope disclosure fire on most of the book
  (§11.3).
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
`tests/integration/test_cold_start.py`, the upload round trip and the reconciled book by
`tests/integration/test_walkthrough.py`, the endpoint table by `tests/api/test_openapi.py`.

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

## Non-goals

New features. If the walkthrough wants a capability that does not exist, the answer is a
sentence in Limitations, not a slice 7 implementation. The one exception is a defect the
walkthrough surfaces in something already claimed to work — that gets fixed, because the
README is the claim.