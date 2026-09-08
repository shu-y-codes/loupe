/**
 * The canvas vocabulary as React: Stack, Row, Pill, Stat, Callout, Table, Caption.
 *
 * These are the components the canvases compose from (`cursor/canvas`'s `Stack`, `Row`,
 * `Pill`, `Stat`, `Callout`, `Table`), re-implemented against this app's tokens. Having them
 * as primitives rather than ad-hoc `<div style>` is what keeps the editorial language
 * consistent across two pages — and it is the list a reviewer can check against the canvas.
 *
 * What is deliberately absent: anything with a gradient, a box-shadow, an emoji status, a
 * rainbow palette or KPI-sized type. A `Stat` here is a small number over a label, not a
 * dashboard tile.
 */

import type { CSSProperties, ReactNode } from "react";
import { theme } from "../theme/theme";

type Tone = "primary" | "secondary" | "tertiary" | "quaternary";

const TONE: Record<Tone, string> = {
  primary: theme.text.primary,
  secondary: theme.text.secondary,
  tertiary: theme.text.tertiary,
  quaternary: theme.text.quaternary,
};

export function Stack({
  gap = 12,
  children,
  style,
  ...rest
}: {
  gap?: number;
  children: ReactNode;
  style?: CSSProperties;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "style" | "children">) {
  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap, minWidth: 0, ...style }}
      {...rest}
    >
      {children}
    </div>
  );
}

export function Row({
  gap = 8,
  align = "center",
  wrap = false,
  children,
  style,
  ...rest
}: {
  gap?: number;
  align?: CSSProperties["alignItems"];
  wrap?: boolean;
  children: ReactNode;
  style?: CSSProperties;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "style" | "children">) {
  return (
    <div
      {...rest}
      style={{
        display: "flex",
        gap,
        alignItems: align,
        flexWrap: wrap ? "wrap" : "nowrap",
        minWidth: 0,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Text({
  tone = "primary",
  size = "body",
  weight = "normal",
  children,
  title,
  style,
}: {
  tone?: Tone;
  size?: "small" | "body" | "count";
  weight?: "normal" | "semibold";
  children: ReactNode;
  title?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      title={title}
      aria-description={title}
      style={{
        color: TONE[tone],
        fontSize: `var(--size-${size})`,
        fontWeight: weight === "semibold" ? 600 : 400,
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/** Quiet context under a heading. The Streamlit `st.caption` slot. */
export function Caption({ children }: { children: ReactNode }) {
  return (
    <div style={{ color: theme.text.tertiary, fontSize: "var(--size-small)" }}>{children}</div>
  );
}

export function Pill({
  active = false,
  onClick,
  children,
  ...rest
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "children">) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        border: `1px solid ${active ? theme.stroke.focused : theme.stroke.primary}`,
        background: active ? theme.fill.primary : theme.bg.elevated,
        color: active ? theme.text.primary : theme.text.secondary,
        borderRadius: 999,
        padding: "3px 10px",
        fontSize: "var(--size-small)",
        cursor: onClick ? "pointer" : "default",
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * A Pill's look without a Pill's behaviour.
 *
 * A grain cell inside a clickable table row is a label, and a `<button>` there is a focus stop
 * that does nothing — worse, one that swallows the row's own activation.
 */
export function Badge({ children }: { children: ReactNode }) {
  return (
    <span
      style={{
        border: `1px solid ${theme.stroke.primary}`,
        borderRadius: 999,
        padding: "1px 8px",
        fontSize: "var(--size-small)",
        color: theme.text.secondary,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/** A small number over a label. Not a KPI tile — the value is body-plus, never huge. */
export function Stat({ value, label }: { value: string; label: string }) {
  return (
    <Stack gap={2}>
      <span style={{ fontSize: "var(--size-count)", fontWeight: 590 }}>{value}</span>
      <Text size="small" tone="tertiary">
        {label}
      </Text>
    </Stack>
  );
}

const CALLOUT_ACCENT = {
  info: theme.accent.primary,
  warning: theme.diff.stripRemoved,
  danger: theme.category.red,
} as const;

/**
 * A bordered note with a left rule and a title.
 *
 * This is where Streamlit's `⚠️ st.warning` went. Synthetic disclosure is a warning Callout,
 * not an emoji: the emoji was doing the work of saying "this matters", and a titled block with
 * a coloured rule says it in the page's own language.
 */
export function Callout({
  tone = "info",
  title,
  children,
  role,
}: {
  tone?: keyof typeof CALLOUT_ACCENT;
  title?: string;
  children: ReactNode;
  role?: string;
}) {
  return (
    <div
      role={role}
      style={{
        borderLeft: `3px solid ${CALLOUT_ACCENT[tone]}`,
        border: `1px solid ${theme.stroke.secondary}`,
        borderLeftWidth: 3,
        borderLeftColor: CALLOUT_ACCENT[tone],
        background: theme.bg.sunken,
        borderRadius: "0 var(--radius) var(--radius) 0",
        padding: "10px 12px",
      }}
    >
      {title ? (
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      ) : null}
      <div style={{ color: theme.text.secondary }}>{children}</div>
    </div>
  );
}

export interface Column<Row> {
  key: string;
  header: string;
  /** One sentence on a named box. Column headers get help; cells do not. */
  help?: string;
  width?: number | string;
  align?: "left" | "right";
  render: (row: Row) => ReactNode;
}

/**
 * Compact editorial table (the `contract-family-tiles` canvas's typography).
 *
 * Wide content scrolls inside its own container rather than pushing the page sideways, and a
 * row is clickable only when `onSelect` is given — the Overview table needs that; the issues
 * table must not have it.
 *
 * **A clickable row is not a button.** Putting `role="button"` on a `<tr>` replaces the row
 * role, which is what tells a screen reader it is in a table at all: the column headers stop
 * being announced with the cells and the grid stops being navigable as a grid. So the row
 * keeps its row semantics and carries `onClick` as a pointer convenience only, and the
 * keyboard-reachable control is a real `<button>` inside a cell — see `RowAction`.
 */
export function Table<Row>({
  columns,
  rows,
  rowKey,
  onSelect,
}: {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row, index: number) => string;
  onSelect?: (row: Row) => void;
}) {
  return (
    <div style={{ overflowX: "auto", border: `1px solid ${theme.stroke.secondary}`, borderRadius: "var(--radius)" }}>
      <table
        style={{
          borderCollapse: "collapse",
          width: "100%",
          fontSize: "var(--size-body)",
        }}
      >
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                title={column.help}
                aria-description={column.help}
                style={{
                  textAlign: column.align ?? "left",
                  padding: "8px 10px",
                  borderBottom: `1px solid ${theme.stroke.primary}`,
                  color: theme.text.secondary,
                  fontWeight: 600,
                  fontSize: "var(--size-small)",
                  whiteSpace: "nowrap",
                  width: column.width,
                  position: "sticky",
                  top: 0,
                  background: theme.bg.editor,
                }}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row, index)}
              onClick={onSelect ? () => onSelect(row) : undefined}
              style={{
                cursor: onSelect ? "pointer" : "default",
                background: index % 2 ? theme.bg.sunken : theme.bg.editor,
              }}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  style={{
                    padding: "8px 10px",
                    borderBottom: `1px solid ${theme.stroke.tertiary}`,
                    textAlign: column.align ?? "left",
                    verticalAlign: "top",
                  }}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Divider() {
  return <hr style={{ border: 0, borderTop: `1px solid ${theme.stroke.secondary}`, margin: 0 }} />;
}


/**
 * The keyboard-reachable half of a clickable row: a real button, styled as the cell's text.
 *
 * It carries the whole instruction as its accessible name ("Open ESZ25 minute in Review")
 * because a button announced only as "ESZ25" tells a screen-reader user what it is called and
 * not what it does.
 */
export function RowAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      style={{
        background: "none",
        border: 0,
        padding: 0,
        margin: 0,
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
      }}
    >
      {children}
    </button>
  );
}
