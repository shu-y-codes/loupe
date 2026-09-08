/**
 * The same tokens, as values, for the SVG charts.
 *
 * A chart cannot take a CSS variable everywhere it needs a colour — a `<path stroke>` can,
 * but a computed y-position or a colour picked by a branch cannot — so the palette exists
 * twice: once in `tokens.css` for layout, and here for the marks. Keeping the names identical
 * is what stops the two drifting.
 */

export const theme = {
  text: {
    primary: "var(--text-primary)",
    secondary: "var(--text-secondary)",
    tertiary: "var(--text-tertiary)",
    quaternary: "var(--text-quaternary)",
  },
  stroke: {
    primary: "var(--stroke-primary)",
    secondary: "var(--stroke-secondary)",
    tertiary: "var(--stroke-tertiary)",
    focused: "var(--stroke-focused)",
  },
  fill: {
    primary: "var(--fill-primary)",
    secondary: "var(--fill-secondary)",
  },
  bg: {
    editor: "var(--bg-editor)",
    elevated: "var(--bg-elevated)",
    sunken: "var(--bg-sunken)",
  },
  accent: { primary: "var(--accent-primary)" },
  category: {
    red: "var(--category-red)",
    orange: "var(--category-orange)",
    blue: "var(--category-blue)",
  },
  diff: { stripRemoved: "var(--diff-strip-removed)" },
  mark: {
    neutral: "var(--neutral-mark)",
    absent: "var(--absent-mark)",
    volume: "var(--volume-mark)",
  },
} as const;
