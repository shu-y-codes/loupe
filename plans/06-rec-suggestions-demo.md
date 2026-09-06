# 06 — Reconciliation, suggestions, demo

**Goal.** `REC.*` when both frequencies exist; report-only suggestions; labelled
defect injection with a ground-truth manifest.

**Status.** done — 2026-09-07

Amended 2026-09-06 after slice 5 shipped. Slice 5 left three forward references into this
slice and created one coupling it could not see: `dq.dq_finding.frequency` for a `REC.*`
finding is now load-bearing, because the Risk closing-day callout filters on it. Done-when 2
gains the convention; done-when 6 through 9 are new. One instruction slice 5 wrote has been
reversed — see done-when 8.

## Done when

1. ✅ `REC.*` / pattern / suggestion shapes already live in `specs/dq-rules-and-scoring.md`
   (slice 2 promote). No further promote from `_notes/cursor/04-dq-rules-and-scoring.md`.
2. Reconciliation findings only when daily + minute exist for the same contract
   (OHLC disagreement coverage-gated, volume shortfall, session only-in-one,
   close-convention info). Score includes reconciliation when in scope.

   **The `frequency` / `compare_frequency` convention is settled in spec** — see
   `specs/dq-rules-and-scoring.md` §8, "Which side goes in `frequency`". It is load-bearing
   rather than cosmetic: slice 5's closing-day callout filters `SETTLEMENT_RULES` at
   `frequency = 'daily'` ([inventory.py](../src/loupe/quality/inventory.py)), so a `REC.*`
   finding written on the wrong side is dropped silently instead of failing. Assert it.

3. Patterns (lift) and suggestions with rationale / `expected_effect`, shown as text.
   No apply/dismiss; no finding override.
4. **The two v1 insights routes, deferred here from slice 4.** `GET /v1/insights/patterns`
   and `GET /v1/insights/suggestions` are v1 in `specs/api-contract.md` §7 and were held
   back from [04-api.md](04-api.md) because nothing backed them — done-when 3 is the layer
   they call. Two handlers and their contract tests added to the app slice 4 built, in
   `src/loupe/api/` and `tests/api/`, calling the reports above; no lift or rationale maths
   in a handler. `min_lift` / `min_support` filter the pattern list; suggestions are
   report-only text and carry no apply path.
5. Labelled injection utility + manifest — never silently corrupt pristine samples.
   Lead demos with real findings plus injected daily defects.

   **Measured before building, and it corrected the assumption.** An earlier draft of this
   done-when claimed injected daily defects were what made the Risk screen demonstrable at
   all. That is false for this corpus. Over the 48 fetched files, 40 contracts:

   | | contracts |
   |---|---|
   | both grains — `REC.*` in scope, Risk fully evidenced | 8 |
   | daily only — reconciliation out of scope | 32 |
   | minute only | 0 |

   30,102 daily rows. **Every contract has daily records**, so closing-day callouts and the
   settlement trend populate across the whole book without injecting anything. Injection is
   what it always was: labelled ground truth for the defect types the real corpus happens not
   to contain, and a manifest to test the labels against.

   Two consequences worth carrying. **Mixed scope is the demo's default, not an edge case** —
   32 of 40 contracts score over five dimensions and 8 over six, so slice 5's `†` mark and the
   scope disclosure fire on most of the inventory. And the "No daily records loaded" notice
   will not appear on the fetched corpus at all; it is reachable only through an upload, which
   is where it should be tested.

6. **Reconciliation enters the score, which means `scoring.py` changes.**
   [`_reconciliation_note`](../src/loupe/quality/scoring.py) reports *"no reconciliation
   evidence has been computed for this contract"* for a dual-grain contract, so the dimension
   is **always** out of scope today. This slice adds the in-scope path: §8.6's sub-score over
   reconcilable sessions, §11.3's renormalisation to a 1.20 denominator when it applies, and a
   `reconciliation` row in `mart.dq_metric_daily` at `frequency = 'cross'` (§11.1). Neither
   table constrains `frequency`, so `'cross'` needs no DDL change.

   Two things §11.3 and §8.6 forbid, and a test should hold: a contract with no reconcilable
   sessions gets **no** reconciliation score — not 100, not 0 — and `REC.CLOSE_CONVENTION`
   never enters the numerator. Once evidence exists that reason is false and must go; it is
   rendered verbatim under the score (`specs/loupe-ui-design.md`), so a stale one is shown to
   a reader as a fact about their contract.

7. **The two catalogue constants slice 5 left instructions for.** `RULE_SUBJECT_FIELD` gains
   `REC.VOLUME_SHORTFALL` → `volume` under §11.7's two-part test; session-only-in-one is
   record-shaped and close-convention is diagnostic, so both stay absent. `SETTLEMENT_RULES`
   gains **nothing** — see done-when 8. `src/loupe/quality/catalogue.py` is edited, and the
   `RULE_SUBJECT_FIELD` denominator (`considered` / `total` on `worst_field`) shifts as a
   result, which is the intended behaviour and not a regression.

8. **Corroboration — and the §11.6 instruction that has been reversed.** Slice 5 wrote into
   §11.6 that this slice would add `REC.CLOSE_CONVENTION` to `SETTLEMENT_RULES`. That was
   wrong and the spec now says so: the rule is `info`, it fires on the *expected* difference
   between a settlement and a last trade (§8.4), and the Closing-day column is what a risk
   manager reads as what is **wrong** with a settlement.

   Reconciliation's contribution to the Risk view is attribution, not another callout. A daily
   `CON.CLOSE_OUT_OF_RANGE` is already visible in the daily file; what one file cannot say is
   which of its numbers to distrust. §8.7 defines the three states — `confirmed`, `disputed`,
   `not_comparable` — composed in `quality` from findings that already exist, writing no
   finding and entering no score. The Specifics **Why** cell states it beside the finding it
   qualifies (`specs/loupe-ui-design.md`, Risk → Specifics).

   **It reaches the UI on the finding envelope**, settled in `specs/api-contract.md` §6.2: a
   `corroboration` object on every `GET /v1/dq/findings` row and on `GET /v1/dq/findings/{id}`,
   resolved in one pass over the run's `REC.*` findings rather than per row. A route of its own
   was the alternative and is worse — it would let a client render the finding without the
   qualification that changes what it means. Note the **fourth** answer the envelope adds:
   absent means *corroboration does not apply to this finding*, which is not `not_comparable`.

   **The four states need a fixture each, and the test must see all four.** Per
   `specs/loupe-solution-design.md` §13, "A test that cannot fail is worse than no test": an
   implementation returning `not_comparable` unconditionally satisfies any assertion written
   only about `not_comparable`, and that is the likeliest way this ships broken. Assert the
   four are pairwise distinct over four inputs chosen to produce them.

9. **The UI lights up when done-when 4 lands, and only the unbuilt path is tested today.**
   `src/loupe/ui/specifics.py` already calls both routes: `_report()` renders "not in this
   build" and `_address()` returns the pending sentence. Neither needs new code when the
   routes ship — which is exactly the risk, because `tests/ui/test_pages.py` stubs the 404 and
   will keep passing whether or not the populated path works — the exact shape §13 now
   forbids. Add `tests/ui/` cases for patterns and suggestions returning rows, and for
   **Address** carrying real suggestion text; keep the 404 cases, since both sides of that
   branch matter. The built-path assertions must fail if `_report()` is stubbed to render
   nothing, which is worth checking once by hand before trusting them.

## Files to create

- `quality/` — `REC.*` runners, pattern/suggestion reports (extend slice 2)
- `src/loupe/quality/corroboration.py` — the three states of §8.7, in their own module. Not a
  runner and not part of the scorer: it writes no finding and enters no score, and filing it
  with either would invite a later contributor to make it do what its neighbours do.
- Injection helper + manifest (derived from samples, not committed vendor files)
- Tests for `REC.*`, lift, suggestion payload shape, injection labels

Edited: `src/loupe/api/` and `tests/api/` — the two routes from done-when 4;
`src/loupe/quality/scoring.py` — the reconciliation in-scope path (done-when 6);
`src/loupe/quality/catalogue.py` — `RULE_SUBJECT_FIELD` (done-when 7);
`src/loupe/api/models.py` — the `corroboration` object on `Finding` (done-when 8);
`tests/ui/` — the populated path (done-when 9).

Already amended ahead of the build, so this slice implements rather than decides:
`specs/dq-rules-and-scoring.md` §8 (the `frequency` convention), §8.7 (corroboration, and the
module it lives in) and §11.6 (the closed settlement set); `specs/api-contract.md` §6.2 (the
`corroboration` object); `specs/data-model.md` §4 (the cross-reference);
`specs/loupe-ui-design.md` (the corroborated **Why** cell).

## Tests

`REC.*` skipped/empty when only one frequency; volume shortfall one direction;
injection rows labelled and listed in the manifest; suggestions have no apply path.
Both routes return their contract shape; `min_lift` / `min_support` filter; the
suggestions payload exposes no apply or dismiss link.

A `REC.OHLC_DISAGREE` finding records `frequency = 'daily'` and a `REC.VOLUME_SHORTFALL`
records `'minute'`, so the closing-day filter keeps working and neither is silently dropped.
A settlement callout is asserted **present** on a daily `REC`-corroborated contract, not only
absent elsewhere — slice 5 shipped that assertion vacuously and it is the pattern §13 names.
Corroboration returns `confirmed` on a session the tape agrees with, `disputed` where
`REC.OHLC_DISAGREE` fired, `not_comparable` below `min_coverage_pct` or with one grain, and is
**absent** on a finding it does not apply to — four answers, asserted apart, because
collapsing them is the failure §8.7 exists to prevent. A contract with no reconcilable
sessions has no reconciliation score rather than 100 or 0, and `REC.CLOSE_CONVENTION` stays
out of the numerator.
The patterns and suggestions panels render rows when the routes answer, and the Address column
carries real text rather than the pending sentence.

## Attach

- `specs/loupe-solution-design.md` §9 (reconciliation, patterns, demo defects)
- `specs/api-contract.md` §7 (the two routes)
- `specs/loupe-ui-design.md` (Analyst specifics; report-only)
- `specs/dq-rules-and-scoring.md` (incl. `REC.*`, §8.7 corroboration, §11.6 the closed
  settlement set, §11.7 subject fields, patterns, suggestions)
- `specs/loupe-solution-design.md` §2 (why the Risk persona is advised to load both grains)
- `specs/sample-corpus.md`

## Non-goals

Apply suggestion → mutate `dq_rule` / calendar → re-run. Finding override. AI
narratives. Those stay extensions (solution brief §14).
