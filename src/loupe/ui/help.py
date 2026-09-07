"""One sentence per named box, in this page's language.

`specs/loupe-ui-design.md` puts help on named boxes — family cards, score-caption jargon,
and aggregated-issue column headers — not on every grid cell. What / What we did *cells*
and picture sentences are already the explanation, so they get nothing extra. Rule IDs
never appear in a hover; they are a caption under the chart or picture.
"""

from __future__ import annotations

#: Family cards, keyed by the API `family` id.
CARDS: dict[str, str] = {
    "gaps": "Missing timestamps and absent sessions — holes in the expected grid, not a "
    "quiet market.",
    "duplicates": "Exact copies and key conflicts on the same timestamp. Duplicate files "
    "are listed in the sidebar, not here.",
    "invalid": "Prices or volumes that cannot be right on their own, including a close "
    "outside the bar. Outliers are off this strip.",
    "patterns": "Standing concentrations, corrected for how often that bucket appears in "
    "the records.",
}

#: Column headers on the aggregated issues table.
COLUMNS: dict[str, str] = {
    "What": "The issue in the rule catalogue's words, or a pattern narrative. Not a rule ID.",
    "Days": "Distinct trade dates in this window that carry the issue.",
    "Records": "How many records the envelope counted for this issue.",
    "What we did": "What default cleaning did, from the changelog. This page does not apply "
    "a new rule.",
}

#: Jargon that needs a sentence wherever it appears.
JARGON: dict[str, str] = {
    "scope_signature": "Which quality dimensions this score was measured over. Equal "
    "signatures are comparable; unequal ones are not the same measurement.",
    "vwap": "Rolling 15-minute volume-weighted average price. Needs minute bars; a "
    "daily-only contract cannot have one.",
    "marked sessions": "How many dates the selected check flags on the chart.",
}
