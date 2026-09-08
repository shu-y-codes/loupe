/**
 * Chart plumbing: the x window, the y extent, and the identity a zoom belongs to.
 *
 * Kept out of the components because it is the part that has rules. `chartScopeKey` decides
 * *when a zoom resets*, and that decision is spec text: contract, quality grain or From / To
 * make a new chart identity and reset to the filtered extent; a family-only change keeps the
 * identity and preserves the zoom (`specs/loupe-ui-design.md`, Zoom and identity).
 *
 * The charts are custom SVG rather than a library because none of the obvious ones can draw
 * the mark this page most needs: an **absent** column is a dashed labelled column where a
 * candle would be, and a candlestick library given no OHLC draws a zero bar or nothing at all.
 * A zero-filled bar for a settlement that never arrived is the exact lie the overlay exists to
 * prevent.
 */

export interface Extent {
  /** Index of the first visible slot. */
  start: number;
  /** Index one past the last visible slot. */
  end: number;
}

export const IDENTITY = (count: number): Extent => ({ start: 0, end: count });

/** Clamp a window to the data, and never let it collapse below a few slots. */
export function clampExtent(extent: Extent, count: number, minSlots = 3): Extent {
  const span = Math.max(minSlots, Math.min(count, Math.round(extent.end - extent.start)));
  let start = Math.round(extent.start);
  if (start < 0) start = 0;
  if (start + span > count) start = Math.max(0, count - span);
  return { start, end: start + span };
}

/** Zoom around a fractional position in the current window. `factor > 1` zooms out. */
export function zoomExtent(
  extent: Extent,
  count: number,
  factor: number,
  focus: number,
): Extent {
  const span = extent.end - extent.start;
  const anchor = extent.start + span * focus;
  const next = span * factor;
  return clampExtent({ start: anchor - next * focus, end: anchor - next * focus + next }, count);
}

export function panExtent(extent: Extent, count: number, slots: number): Extent {
  return clampExtent({ start: extent.start + slots, end: extent.end + slots }, count);
}

/**
 * Stable for family-only reruns; changes with scope or with the returned data extent.
 *
 * The returned extent is part of it because a filter that returns different dates is a
 * different picture even when the scope object looks the same.
 */
export function chartScopeKey(
  scope: Record<string, unknown>,
  rows: readonly object[],
  field: string,
): string {
  const values = rows
    .map((row) => (row as Record<string, unknown>)[field])
    .filter((value): value is string => value !== null && value !== undefined)
    .map(String)
    .sort();
  const first = values[0] ?? "";
  const last = values[values.length - 1] ?? "";
  const parts = Object.keys(scope)
    .sort()
    .map((key) => `${key}=${String(scope[key] ?? "")}`);
  return [...parts, `extent=${first}..${last}`].join("|");
}

/**
 * The min and max of a series, in one pass.
 *
 * `Math.max(...values)` is the obvious spelling and it is a crash: the spread becomes one
 * argument per element, and a real VWAP window is 114,477 of them — `RangeError: Maximum call
 * stack size exceeded`, found by a live pass against the sample corpus rather than by a test
 * over a two-point fixture. Nothing in this app may spread a series into a call.
 */
export function extremes(values: readonly number[]): { min: number; max: number } | null {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  return min === Infinity ? null : { min, max };
}

/**
 * At most `budget` marks across the pane, by bucketing — a selection, never an average.
 *
 * A minute tape is a hundred thousand points and a chart pane is seven hundred pixels wide,
 * so something has to give. What gives is *how many observed points are drawn*, never what any
 * of them says: each bucket is represented by a point that is actually in it. Averaging would
 * be arithmetic on the series, which is `insights`' job and not a widget's
 * (`specs/loupe-solution-design.md` §6).
 *
 * **A bucket holding any null is a break.** Under-reporting a break would draw a connected
 * line across a window whose volume was dropped, which is the one thing
 * `specs/analytics-semantics.md` forbids. Over-reporting its *width* at full zoom-out is
 * visible, honest, and resolves as the reader zooms in.
 */
export function bucketSeries<T>(
  points: readonly T[],
  budget: number,
  value: (point: T) => number | null | undefined,
): { point: T; value: number | null; broken: boolean }[] {
  if (points.length <= budget) {
    return points.map((point) => {
      const v = value(point);
      const present = v !== null && v !== undefined;
      return { point, value: present ? v : null, broken: !present };
    });
  }
  const size = points.length / budget;
  const out: { point: T; value: number | null; broken: boolean }[] = [];
  for (let index = 0; index < budget; index += 1) {
    const from = Math.floor(index * size);
    const to = Math.min(points.length, Math.floor((index + 1) * size));
    if (to <= from) continue;
    let chosen: number | null = null;
    let broken = false;
    for (let cursor = from; cursor < to; cursor += 1) {
      const v = value(points[cursor] as T);
      if (v === null || v === undefined) broken = true;
      else if (chosen === null) chosen = v;
    }
    out.push({ point: points[from] as T, value: chosen, broken });
  }
  return out;
}

/** Nice-ish tick values across a numeric range. Four is enough for a 260px pane. */
export function ticks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

export function formatNumber(value: number): string {
  const magnitude = Math.abs(value);
  const digits = magnitude >= 1000 ? 0 : magnitude >= 10 ? 2 : 4;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** `2025-06-02` → `Jun 2`. Axis labels, not data. */
export function shortDate(iso: string): string {
  const parsed = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** `2025-06-02T17:15:00Z` → `17:15`. */
export function shortTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  });
}
