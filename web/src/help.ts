/**
 * One sentence per named box, in this page's language.
 *
 * `specs/loupe-ui-design.md` puts help on named boxes — family-card **counts**, and
 * aggregated-issue column headers — not on every grid cell. Family names have no `?`.
 * What / What we did *cells* and picture sentences are already the explanation, so they get
 * nothing extra. Rule IDs never appear in a hover; they are a caption under the picture.
 * Overlay marks are a chart legend, not a tooltip.
 *
 * Delivered as a native `title` plus an `aria-description`, not a bespoke tooltip widget: the
 * browser's own affordance is keyboard- and screen-reader-reachable for free, and a hover card
 * this app would have to build is one more thing to get wrong on touch.
 */

/** Family-card counts, keyed by the API `family` id. Attaches to `42 runs`, not "Gaps". */
export const CARDS: Record<string, string> = {
  gaps:
    "Missing timestamps and absent sessions — holes in the expected grid, not a quiet market.",
  duplicates:
    "Exact copies and key conflicts on the same timestamp. Duplicate files are listed in the " +
    "sidebar, not here.",
  invalid:
    "Prices or volumes that cannot be right on their own, including a close outside the bar. " +
    "Outliers are off this strip.",
  patterns:
    "Standing concentrations, corrected for how often that bucket appears in the records.",
};

/** Column headers on the aggregated issues table. */
export const COLUMNS: Record<string, string> = {
  What: "The issue in the rule catalogue's words, or a pattern narrative. Not a rule ID.",
  Days: "Distinct trade dates in this window that carry the issue.",
  Records: "How many records the envelope counted for this issue.",
  "What we did":
    "What default cleaning did, from the changelog. This page does not apply a new rule.",
};

/** Jargon that needs a sentence wherever it appears. */
export const JARGON: Record<string, string> = {
  vwap:
    "Rolling 15-minute volume-weighted average price. Needs minute bars; a daily-only " +
    "contract cannot have one.",
};
