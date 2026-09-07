# 09 — Reviewer-facing UI

**Goal.** One page that names the brief’s four checks and two charts. No persona
selector. Spec the chrome and any backend the widgets need, then rebuild the Streamlit
page against that spec.

**Status.** done — 2026-09-07

Written 2026-09-07. Click-test chrome is [10-reviewer-chrome.md](10-reviewer-chrome.md)
(pending). The README walkthrough is [11-readme-walkthrough.md](11-readme-walkthrough.md)
and must describe the page **after** 10, not Summary / Specifics and not the score caption.

Do not reopen [05-ui.md](05-ui.md) or [08-ingest-chrome.md](08-ingest-chrome.md). Those
slices stay **done**. Amend the specs they pointed at; leave the plan files as history.

## The change

The brief is organised around **named checks and two charts**. The shipped UI is organised
around **personas and a score**. Those are not the same taxonomy.

Replace the persona-shaped Summary / Specifics page with the layout proven in
[chart-issue-overlay.canvas.tsx](/Users/shu/.cursor/projects/Users-shu-Documents-loupe/canvases/chart-issue-overlay.canvas.tsx):
four family cards, Daily OHLCV then 15-minute VWAP (full width, family marks on the
selected check), picture of the selected family **below** VWAP so expanding it does not
shove the charts.

**Keep** the current sidebar except the persona radio: trade dates, Load demo data, Inject
defects, ingested-file list, CSV conversion mark, empty-store copy. Law today:
`specs/loupe-ui-design.md` (Sidebar). Ingest path does not change (`specs/api-contract.md`
§4; slice 8).

**Ditch** the Risk / Trader / Analyst view selector. One page. Filter by **contract and
date** (already sidebar dates; contract picker is a spec decision below, not a leftover
persona).

Visual source for the main column (research, not law until promoted): the canvas above.
`_notes/brainstorm/reviewer-facing-quality.md` and
`_notes/brainstorm/overlay_canvas.py` are scrapbook — promote, do not implement from them.

## Filename

Rewrite **`specs/loupe-ui-design.md` in place.** No `*-v2.md`. Git is the version trail
(`.cursor/rules/docs-authority.mdc`). One-line revision at the top. Solution brief §12
stays the pointer + invariants; it must not keep a second, persona-shaped truth.

## Overlay grammar (promote this; do not re-litigate in code)

Key candles on the **selected family**, not `max_severity`. `max_severity` stays on the
bar envelope for the publish gate (`specs/analytics-semantics.md` §3.3). The UI stops
painting with it.

| Family | Daily OHLCV | 15-min VWAP |
|---|---|---|
| Gaps | Pin / triangle on session-open holes; dashed column if the settlement never arrived. Never a zero-filled bar. | Named break where window volume was dropped. |
| Duplicates | Pin on the kept timestamp. Do not recolor the body. | Usually none. |
| Invalid values | Paint that candle; volume pane for volume defects. | Only if cleaning dropped the window. |
| Recurring patterns | Band every participating session. | Shade the concentrating hour. |

`OUT.*` stays off this strip (optional in the brief). Rule IDs are a caption, never the
headline. Captions under the charts **explain the marks**, they do not argue a proposal.

Family → rule map (engine unchanged; labelling + grouping). Promote into the UI spec and
the catalogue, same home as `SETTLEMENT_RULES`:

| Card | Counts toward it | Do not mix in |
|---|---|---|
| Gaps | `CMP.MISSING_TIMESTAMP`, `CMP.SESSION_MISSING`, `CMP.PARTIAL_SESSION` | `CMP.NULL_FIELD` (invalid *value*) |
| Duplicates | `UNQ.EXACT_DUPLICATE`, `UNQ.KEY_CONFLICT` | Duplicate *files* (ingest list) |
| Invalid values | `VAL.*` plus `CON.HIGH_LT_LOW` / open-or-close outside range | `OUT.*` |
| Recurring patterns | `GET /v1/insights/patterns` narratives | A count of findings as the lead |

## Settle in the UI spec (done-when 1), not in widgets

Do not leave these for the Streamlit rebuild:

1. **Contract grain.** Canvas is one contract. Today’s Risk inventory is the book. The
   brief asks to filter by contract and date. Spec: four cards and both charts are
   **one selected contract** in the sidebar (with the date window). A book strip is an
   extension unless the spec says otherwise.
2. **Score / ATTN inventory.** The four cards lead. Score can remain a **caption** under
   the cards (one trust line, `scope_signature` still required —
   `specs/dq-rules-and-scoring.md` §11.3). Do not keep a competing persona Summary table
   unless the spec names a thin inventory for switching contract.
3. **Aggregated issues.** Replace Why-as-code / one-row-per-finding with one row per
   *(family, plain-language issue)* in the window (What / Days / Records / What we did).
   Changelog stays the source of “what we did”; the widget does not re-derive cleaning.
4. **Picture of the issue** lives under VWAP (Gaps ribbon, duplicate two-row table,
   invalid broken cell, patterns sentence + histogram). Same family as the cards / overlay.
5. **Help copy** is one page’s language, not “in that persona’s language”.

## Backend plumbing to spec (then build)

Do not join findings onto candles in a Streamlit callback (solution brief §6). Spec the
shape, then a `quality` helper + route (or fields on envelopes the page already fetches).

Likely — confirm in `specs/api-contract.md` during done-when 2, do not invent a fifth
store:

- **Family membership** in `quality/catalogue.py` (named set + rationale, like
  `SETTLEMENT_RULES`). Tests: a rule is in exactly one of the four strip families or in
  “off-strip” (`OUT.*`, and anything the spec leaves off).
- **Card counts** for the selected contract × window: findings (and pattern rows) grouped
  by family. Zero is a real answer (“check ran”). Prefer composing this in `quality` over
  four client-side `rule_id=` filters.
- **OHLCV overlay** for the selected family: per `trade_date` in the window, marks the UI
  can draw without knowing rule IDs (partial-gap / absent / duplicate / invalid /
  pattern-member). Absent settlements come from the expected grid vs `mart.bar_daily`,
  not from colouring a bar that does not exist (`CMP.SESSION_MISSING` — no zero-filled
  bar, `specs/analytics-semantics.md` §3.4). Minute `CMP.MISSING_TIMESTAMP` must be able
  to mark a **derived daily** session when that is the chart on screen; today’s
  frequency-aware `max_severity` join is the wrong overlay key.
- **VWAP** already returns `NULL` windows. The panel names the break; no new formula.
  Daily-only still keeps the panel and says “needs minute bars”.
- **Aggregated issues** from findings + `GET /v1/dq/changelog` (already aggregated). Plain
  language from `dq.dq_rule.name` / changelog labels, not `OUT.RETURN_MAD · date`.
- **Patterns** already `GET /v1/insights/patterns`. Card count = standing patterns in
  window, not finding count.

Do not change rule triggers, scores, or cleaning policy unless a spec sentence is actually
wrong. This slice is labelling, grouping, overlay payloads, and chrome.

## Done when

### Spec — first, as for every slice

1. **`specs/loupe-ui-design.md` rewritten** as the one-page reviewer UI: sidebar (no
   persona), four cards, overlay grammar, both charts, picture-below-VWAP, aggregated
   issues, tooltips, empty / daily-only / no-finding states. Wireframe matches. Personas
   section and per-persona Summary / Specifics wireframes are gone, not commented out.

2. **`specs/loupe-solution-design.md` agrees.** §2 is no longer three UI views — rewrite
   as product questions the one page answers (trust + what it looks like, §1). Locked
   decision 6: drop “Personas = view selector”; keep “No authentication.” §12 becomes
   pointer + invariants for the new chrome (cards, overlay, charts order, picture below
   VWAP, report-only). §13 UI tier: no persona-switch test. §15 data-flow: drop
   `view=Trader`. §16 / §17 checkboxes and slice 5 blurb. Doc-map row at the top
   (“Persona UI…” → the new page). Advise-both-grains stays (reconciliation still needs
   two files); it is no longer “aimed at Risk.”

3. **Sibling specs — grep and patch so they do not teach the old page.** Pointers, not a
   second UI spec:

   | Spec | Why it is touched |
   |---|---|
   | `specs/api-contract.md` | Family rollup / overlay fields or route; §6.1 “every persona’s Summary table”; §8 “Personas are a UI view selector”; §9 table still maps the four checks — keep it honest. |
   | `specs/dq-rules-and-scoring.md` | Family set (or pointer to catalogue); drop “Displayed on every persona dashboard” / “Risk persona” where that sentence would still teach three views. §11.6 Closing-day / `SETTLEMENT_RULES` may still exist as *data*; they are not a Risk-only column unless the new UI spec keeps a settlement callout. |
   | `specs/analytics-semantics.md` | Only if overlay join is specified here (findings × daily bar). Do not redefine `max_severity`. |
   | `specs/data-model.md` | Only if a sentence still says “the analyst persona has nowhere to go.” No DDL unless overlay needs a column the mart does not have — prefer query-time marks. |
   | `specs/sample-corpus.md` | Only if a sample *claim* is about a persona screen. Unlikely. |

   `README.md` product blurb (personas) waits for slice 9, except a one-line pointer if the
   root README would otherwise contradict the spec the day this lands.

   **Do not edit** `_notes/founding/`. Cursor rules that say “UI → `loupe-ui-design.md`”
   stay valid because the filename does not change.

4. **API contract names the overlay/card envelopes** (done-when 3’s api row, fully
   shaped). A widget that can only be built by grouping `findings[]` in Python is a failed
   done-when.

### Then code

5. **`quality` + `api`:** catalogue family set; helper(s) for card counts and OHLCV
   overlay marks; route or fields from done-when 4. Tests in `tests/quality/` /
   `tests/api/` — a gap marks an absent day with no bar row; invalid paints a present bar;
   `OUT.*` does not count on a card.

6. **`ui`:** one page. Sidebar without persona. Cards select family (and overlay). Charts
   then picture. Thin widgets; HTTP only. No SQL, no family membership lists in callbacks.

7. **Tests.** `AppTest`: persona radio absent; four family labels visible after a stubbed
   load; selecting Gaps vs Invalid changes overlay marks, not only a caption; VWAP panel
   stays on daily-only with the in-place refusal; no apply/override. Replace
   `tests/ui/` cases that assert persona switch / Risk columns / Trader changelog-as-lead.

## Sequencing

Done-when 1–4 (specs) before any widget. 5 before 6. 7 with 6.

Slice 11's walkthrough done-whens that name “open one finding” / Risk columns are rewritten
when this page exists, against this page after slice 10 chrome. Do not start 11 in
parallel with 9; 10 is the click-test chrome and blocks 11.

## Files

- `specs/loupe-ui-design.md` — replace.
- `specs/loupe-solution-design.md` — §2, §3.6, §12, §13 UI row, §15–17, doc-map.
- `specs/api-contract.md` — overlay/card envelopes; §6.1, §8, §9 as needed.
- `specs/dq-rules-and-scoring.md` — family set / persona-sentence sweep.
- `specs/analytics-semantics.md` / `specs/data-model.md` — only if done-when 3 requires it.
- `src/loupe/quality/catalogue.py` — family membership.
- `src/loupe/quality/` — card rollup + overlay helper (new module if it will not fit
  inventory).
- `src/loupe/api/routes/` — the fields or route from the contract.
- `src/loupe/ui/` — `chrome.py` (persona out; contract in), `app.py` / `summary.py` /
  `specifics.py` / `charts.py` rebuilt to the new spec. Do not leave a dead persona
  branch.
- `tests/quality/`, `tests/api/`, `tests/ui/`.

## Attach

- [chart-issue-overlay.canvas.tsx](/Users/shu/.cursor/projects/Users-shu-Documents-loupe/canvases/chart-issue-overlay.canvas.tsx) (layout + overlay grammar)
- `specs/loupe-ui-design.md` (sidebar to keep; rest to replace)
- `specs/loupe-solution-design.md` §1–3, §6, §12–17
- `specs/api-contract.md` §6, §8, §9
- `specs/dq-rules-and-scoring.md` §11.3, §11.6–11.7
- `specs/analytics-semantics.md` §3.3–3.4
- [10-reviewer-chrome.md](10-reviewer-chrome.md) — click-test chrome; do not reopen this slice
- [11-readme-walkthrough.md](11-readme-walkthrough.md) — blocked on 10
- [05-ui.md](05-ui.md), [08-ingest-chrome.md](08-ingest-chrome.md) — done; do not reopen

## Non-goals

New rules, score formula, cleaning policy, apply/override, auth, file uploader, tick
log, leading with `OUT.*`, a fourth “reviewer” persona, implementing from `_notes/`
before the UI spec is rewritten, starting the README walkthrough against the old page.
