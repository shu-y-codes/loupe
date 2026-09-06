"""One sentence per named box, in that persona's language.

`specs/loupe-ui-design.md` fixes both the policy and most of the wording: help goes on **named
boxes** — KPI tiles and column headers — and not on every grid cell. The cells that explain
themselves get nothing, because a tooltip on an explanation is noise:

* Why / Impact / Address rows are already the explanation.
* The findings **What** column is already the explanation.
* Rule IDs and `expected_effect` JSON never appear in a hover.

Keeping the strings here rather than inline at each `st.metric` call means the vocabulary is
reviewable in one place, and a persona's language stays consistent across the two modules that
use it.
"""

from __future__ import annotations

#: KPI tiles, keyed by the label they sit under.
TILES: dict[str, str] = {
    # Risk
    "DQ score": "Weighted quality index across the dimensions in scope, 0-100. A navigation "
    "tool, not a grade — open a contract to see which dimension is dragging.",
    "Book hit": "How many loaded contracts hold an error or critical finding, out of all of "
    "them.",
    "Completeness": "Share of expected settlement sessions that arrived.",
    "Settlement trend": "Daily completeness over trade dates — how reliably settlements "
    "showed up, not a price history.",
    # Trader
    "Contracts": "Contracts loaded in the current trade-date window.",
    "With warnings": "Contracts carrying at least one open finding of any severity.",
    # Analyst
    "Open findings": "Findings still open across the scope; accepted and resolved ones are "
    "excluded.",
    "Both frequencies": "Contracts holding daily and minute records, so cross-frequency "
    "reconciliation is in scope for them.",
    "Worst field": "The field the most findings implicate, read from which rules fired. "
    "Reads 'not applicable' when no rule that names a field has fired.",
}

#: Column headers. `specs/loupe-ui-design.md` names Warning, Closing-day and Severity.
COLUMNS: dict[str, str] = {
    "Status": "ATTN when the contract holds an open error or critical finding; OK otherwise. "
    "Not a cut-off on the score.",
    "Closing-day": "What is wrong with this contract's settlement record, if anything. Blank "
    "when nothing about the close is in question.",
    "Warning": "The most serious open finding on this contract, in one line.",
    "Score": "Quality index for the contract, taken from its worst frequency.",
    "Findings": "Open findings on this contract across every frequency held.",
    "Top issue": "The most serious open finding on this contract.",
    "Severity": "How the rule fired here: info, warning, error or critical. Error and "
    "critical are the severities default cleaning acts on.",
    "Action": "What default cleaning did: exclude, dedupe_drop, coerce or impute.",
    "Records": "How many records this one decision touched.",
}

#: Module jargon that needs a sentence wherever it appears (`specs/loupe-ui-design.md`).
JARGON: dict[str, str] = {
    "changelog": "Every cleaning decision this run made, as counts. Raw records are never "
    "edited — the clean view is derived from these rows.",
    "raw neighbourhood": "The raw rows around the selected finding, highlighted but not "
    "editable. Daily-grain findings only in this release.",
    "vwap": "Rolling 15-minute volume-weighted average price. Needs minute bars; a "
    "daily-only contract cannot have one.",
    "lift": "How much more often this issue shows up in this bucket than overall.",
}
