# 11 — Grain-honest review

**Goal.** Make every reviewer claim visibly use the same selected data grain, fix the
Invalid picture to show the record it accuses, make recurring-pattern evidence
self-explanatory, and make VWAP zoomable.

**Status.** pending

Written 2026-09-08 after click-testing CLG26 against the demo load.
[10-reviewer-chrome.md](10-reviewer-chrome.md) stays **done**. Do not reopen it.
[12-readme-walkthrough.md](12-readme-walkthrough.md) is blocked on this slice and must
describe the grain-honest page, not today's mixed-frequency claims.
[13-overview-page.md](13-overview-page.md) also waits on this slice for honest Minute/Daily
rows; it does not change Review’s main column.

## Why this slice exists

On CLG26 with no date filter:

- Recurring patterns says **81 standing**, while Issues in this window shows 86 rows.
  The tile counts 81 pattern rows and names only the top narrative; the table silently
  adds 3 aggregated gap types and 2 invalid types because it is not filtered to the
  selected family.
- Invalid values says **15 rows · 6 prices · 9 volumes**, but no candle or volume bar is
  marked. All 15 findings belong to the supplied **daily** records; the chart defaults
  to the finest held grain and therefore draws 314 daily bars derived from the
  **minute** tape. None of the 15 dates is in that plotted series.
- `quality.review._bar_dates()` ignores `mart.bar_daily.source`, so an overlay row can
  say `session=present` because a vendor daily bar exists even when the chart is drawing
  the derived-minute source and has no candle at that date. Invalid paint only applies
  to rows with OHLC, so the mark disappears.
- The Invalid picture compounds this: `_invalid_picture()` takes the first finding,
  defaults a missing subject field to `close`, and always fetches a clean daily mart bar.
  `VAL.ZERO_VOLUME_WITH_RANGE` is a volume rule and is often daily on this corpus, so
  `Broken cell: close` can be false.
- The recurring-pattern picture can caption `patterns[0]` while charting every
  `hour_of_day` pattern, including other rules. Axes are untitled and lift is not shown,
  so the reader cannot tell what the paired bars prove.

These are scope and evidence bugs, not cosmetic disagreements.

## Product decision to promote

### One explicit Quality grain

Add **Quality grain** to the sidebar for a contract holding both frequencies:

- **Minute** — cards, patterns, issues, picture and overlays are filtered to minute
  findings; Daily OHLCV is derived from the minute tape.
- **Daily** — the same surfaces are filtered to daily findings; Daily OHLCV is the
  supplied vendor daily series.
- A minute-only or daily-only contract has no choice control; show the held grain as
  quiet context.
- Default a dual-grain contract to **Minute** (the existing finest-grain API default),
  but echo the choice in the page header/chart subtitle. Never change grain when the
  family changes.

This is preferable to automatically picking daily for Invalid and minute for Gaps:
family-dependent source switching would make cards move under the reader and would hide
which tape is being judged.

**VWAP is always minute.** It gets its own x zoom (intraday timestamps cannot share
OHLCV's trade-date selection). When Quality grain is Daily on a dual-grain contract,
keep the VWAP line because minute data exists, but do not imply that daily findings mark
it: label the panel **Minute tape · context only for Daily quality grain** and suppress
selected-family marks derived from the daily scope. Switching Quality grain to Minute
restores selected-family VWAP marks. A daily-only contract keeps the existing
“needs minute bars” refusal.

### Autoscale on scope change

Both charts initially fit the data returned for the current scope. An interactive zoom
must not leak from the previous contract or grain:

- selecting another contract resets OHLCV/volume and VWAP zoom to that contract's
  returned-data extent;
- changing Quality grain resets OHLCV/volume to the newly selected source extent;
- changing From / To resets both charts to the newly returned filtered extent;
- changing only the family preserves the current zoom where practical because the data
  domain did not change;
- explicit From / To values remain authoritative across contract changes. “Autoscale”
  means fit the intersection of that window and the selected contract's available data,
  not silently clear the user's filters. With no dates set, fit the full available
  extent for the selected contract/grain.

Current risk to remove: OHLCV uses the fixed Vega selection name `ohlcv_x`, while the
chart occupies the same Streamlit element position after a contract rerun. Treat scope
(contract, grain, effective date window/data extent) as chart identity so stale
client-side scale state cannot survive into another dataset. VWAP needs the same
scope-key rule with its own selection name.

## Settle in specs before code

### UI — `specs/loupe-ui-design.md`

1. Sidebar Quality grain control, default, single-grain state, and persistence when
   contract changes.
2. Every family card, selected-family issue row, overlay, picture and OHLCV bar uses the
   selected grain. Name the OHLCV source: **Derived from minute** or **Supplied daily**.
3. Heading becomes **Issues in selected family** (or includes the family label). The
   table does not silently contain the other three families.
4. Invalid picture names the actual subject field and shows evidence at the finding's
   grain. A volume finding never falls back to `close`.
5. VWAP has independent pan/zoom; drag to pan/zoom, double-click to reset. Daily quality
   grain makes it labelled minute context without daily-family marks.
6. Recurring-pattern picture:
   - sentence, rule ID, chart and lift labels refer to one focused
     `(rule_id, dimension)` set;
   - say **Showing 1 of N standing patterns** (or the number of related buckets shown);
   - x-axis title is the plain dimension (for example **Hour of day, exchange local**);
   - y-axis title is **Share (%)**, formatted as percentages;
   - paired series are **Findings** and **Records (exposure)**;
   - label each reported bucket with lift such as **20.5×**;
   - hover names bucket, findings share, records share, lift, support and distinct days;
   - one sentence explains: a findings share much larger than record exposure is
     over-representation; the configured standing threshold, not raw count alone,
     determines inclusion.
   If the top pattern is not hourly, chart that top pattern's dimension. Do not caption
   one dimension while plotting unrelated hourly patterns.
7. **Chart autoscale.** OHLCV/volume and VWAP fit the returned-data extent on initial
   render and reset interaction zoom when contract, Quality grain, or From / To changes.
   Family-only changes do not reset the date domain. Explicit date filters are retained
   and constrain the fitted extent.

### API — `specs/api-contract.md`

Add `frequency=minute|daily` to `GET /v1/dq/checks`, required from this UI and echoed in
`scope.frequency` / `frequency_defaulted`. It filters:

- card findings and pattern rows;
- selected-family `issues[]`;
- overlay dates and source-aware presence;
- picture selection and evidence.

`issues[]` becomes selected-family for this route. This is server-side composition, not
widget-side grouping. If API consumers need all-family issues, they make four family
requests or use the existing findings/summary endpoints; do not overload one UI envelope
with two meanings.

Expand `pattern_histogram` picture data so the client does not derive lift or mix pattern
groups. Include focused rule/dimension, totals shown, axis label, and per bucket:
`share_of_findings`, `share_of_records`, `lift`, `support`, `distinct_days`.

### Analytics and DQ semantics

- `specs/analytics-semantics.md`: point to the existing frequency/source rule:
  `frequency=minute` → derived bars; `frequency=daily` → supplied bars. The reviewer
  page must pass it explicitly.
- `specs/dq-rules-and-scoring.md`: only clarify pattern-picture grouping if needed.
  Detection formula and thresholds do **not** change.
- `specs/loupe-solution-design.md` §12: add explicit grain/source and selected-family
  issues as UI invariants; §17 inserts this slice and moves the README walkthrough to 12.

## Backend shape

1. Thread `frequency` through the checks route and `quality.review.review_checks`.
2. Filter findings and patterns before cards/issues/overlay/picture are composed.
   Pattern filtering uses the pattern's frequency bucket/provenance as specified; do not
   parse narrative text.
3. Make `_bar_dates()` source-aware:
   - minute quality grain → `source='derived'`;
   - daily quality grain → `source='vendor'`.
   Use the same `basis`, contract and date window as the chart.
4. `_invalid_picture()`:
   - subject field = `details.field`, else `RULE_SUBJECT_FIELD[rule_id]`, else an honest
     unknown (never unconditional `close`);
   - use `record_id` / finding frequency to fetch the accused stage record when present;
   - for a daily finding, show the supplied daily record/bar, not a minute-derived bar;
   - return an explicit evidence grain/source in the picture envelope.
   Keeping “first finding in the selected window” is acceptable; do not invent a
   severity ranking.
5. `_pattern_picture()` selects one focused `(rule_id, dimension)` group. Caption and
   buckets come from that group only. Prefer the top-ranked pattern's group; no forced
   `hour_of_day` fallback.

No new store and no new rule execution.

## UI shape

- `chrome.py`: Quality grain selector from `frequencies_available`.
- `app.py` / `client.py`: pass frequency explicitly to checks and Daily OHLCV; pass
  scope identity (contract, grain, effective dates/data extent) to chart rendering.
- `review.py`: source subtitle; selected-family issue heading; honest Invalid evidence
  grain; pattern “showing N” explainer.
- `charts.py`: independently zoomable VWAP; percentage axes, plain series labels, lift
  labels and complete pattern hover; scope-keyed chart identity so OHLCV and VWAP
  autoscale when their dataset changes.

The widget does not filter all-family `issues[]` or calculate lift as a workaround. The
API sends the selected scope and chart-ready evidence.

## Done when

### Specs first

1. UI and API contracts contain the decisions above; sibling specs and solution §12/§17
   agree. No `_notes/founding/` edits.

### Then implementation

2. A dual-grain CLG26 request at `frequency=daily&family=invalid` returns 15 current
   invalid findings/cards and supplied-daily overlay marks; those dates paint candles or
   volume bars in the same supplied-daily series.
3. The same request at `frequency=minute` does not claim those 15 daily invalids and
   draws derived-minute OHLCV. Scope echo makes the difference explicit.
4. `_bar_dates()` cannot report a vendor-only date as present for a derived-minute chart.
5. `VAL.ZERO_VOLUME_WITH_RANGE` picture returns `field=volume` and daily/vendor evidence
   when the selected finding is daily. An intraday fixture returns the source record.
6. `issues[]` contains only the requested family. For CLG26 patterns, tile count and
   pattern issue-row count agree for the selected grain; invalid shows its aggregated
   invalid types without gap/pattern rows.
7. Pattern picture sentence and every bucket share one rule and dimension. Vega/helper
   tests assert percentage axis title/format, Findings vs Records (exposure), lift text,
   and hover fields.
8. VWAP has its own scale-bound x selection and reset caption. At Daily quality grain,
   AppTest shows “minute context” and no selected-family VWAP marks; at Minute grain,
   marks return.
9. Chart tests assert:
   - with no From / To, changing contract replaces the x extent with the new contract's
     returned min/max dates;
   - changing grain or date filters resets OHLCV/volume and VWAP interaction zoom;
   - changing family alone preserves scope identity;
   - explicit dates constrain autoscale and are not silently cleared.
   Browser-pass a manually zoomed contract, then switch to a contract with a materially
   different range; both charts must fit the new scope without double-clicking.
10. Run `uv run pytest tests/quality tests/api tests/ui`; add an integration assertion
   against a dual-grain fixture. Browser-pass CLG26 at both grains before marking done.

## Files

- `specs/loupe-ui-design.md`
- `specs/api-contract.md`
- `specs/analytics-semantics.md` (pointer/clarification)
- `specs/dq-rules-and-scoring.md` (pattern-picture pointer if needed)
- `specs/loupe-solution-design.md` §12, §17
- `src/loupe/quality/review.py`
- `src/loupe/api/routes/dq.py`, `src/loupe/api/models.py`
- `src/loupe/ui/chrome.py`, `app.py`, `client.py`, `review.py`, `charts.py`
- `tests/quality/`, `tests/api/`, `tests/ui/`, focused integration fixture

## Non-goals

Changing rule triggers, `VAL.ZERO_VOLUME_WITH_RANGE` calibration, score formula,
pattern lift formula/thresholds, cleaning policy, `max_severity`, applying suggestions,
book inventory, zooming the gap ribbon, README prose.
