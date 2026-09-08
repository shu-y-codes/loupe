/**
 * Joining bars to overlay marks, and naming what a mark means.
 *
 * The join is **by `trade_date`** and nothing else (`specs/loupe-ui-design.md`, Main column).
 * An absent settlement has an overlay row and no bar row, so the join has to be an outer one:
 * dropping marks without a bar would delete exactly the family this chart exists to show.
 *
 * `overlayStatus` is the chart hover's status field. It reads the **selected family**, never
 * `max_severity` — that field may still arrive on the bar envelope for the publish gate and is
 * ignored here.
 */

import type { Bar, OverlayMark } from "../api/types";

export interface Slot {
  trade_date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  /** `present`, `absent`, or `holiday`. */
  session: string;
  partial_gap: boolean;
  duplicate: boolean;
  invalid: boolean;
  invalid_volume: boolean;
  pattern_member: boolean;
  caption: string;
}

const day = (value: string | null | undefined): string => String(value ?? "").slice(0, 10);

export function overlaySlots(bars: Bar[], marks: OverlayMark[]): Slot[] {
  const byDate = new Map(marks.map((mark) => [day(mark.trade_date), mark]));
  const seen = new Set<string>();
  const slots: Slot[] = [];

  for (const bar of bars) {
    const date = day(bar.trade_date);
    seen.add(date);
    const mark = byDate.get(date);
    slots.push({
      trade_date: date,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume,
      session: mark?.session ?? "present",
      partial_gap: Boolean(mark?.partial_gap),
      duplicate: Boolean(mark?.duplicate),
      invalid: Boolean(mark?.invalid),
      invalid_volume: Boolean(mark?.invalid_volume),
      pattern_member: Boolean(mark?.pattern_member),
      caption: mark?.caption ?? "",
    });
  }

  // A mark with no bar is a session that never arrived. It keeps its column and gets no OHLC —
  // never a zero-filled candle.
  for (const [date, mark] of byDate) {
    if (seen.has(date)) continue;
    slots.push({
      trade_date: date,
      open: null,
      high: null,
      low: null,
      close: null,
      volume: null,
      session: mark.session || "absent",
      partial_gap: Boolean(mark.partial_gap),
      duplicate: Boolean(mark.duplicate),
      invalid: Boolean(mark.invalid),
      invalid_volume: Boolean(mark.invalid_volume),
      pattern_member: Boolean(mark.pattern_member),
      caption: mark.caption ?? "",
    });
  }

  return slots.sort((a, b) => a.trade_date.localeCompare(b.trade_date));
}

/** Plain status for chart hover — selected-family marks, not `max_severity`. */
export function overlayStatus(family: string, slot: Slot): string {
  if (family === "gaps") {
    if (slot.session === "absent") return "gap: session missing";
    if (slot.partial_gap) return "gap: session-open hole";
  } else if (family === "duplicates") {
    if (slot.duplicate) return "duplicate";
  } else if (family === "invalid") {
    if (slot.invalid_volume && !slot.invalid) return "volume defect";
    if (slot.invalid) return "invalid value";
  } else if (family === "patterns") {
    if (slot.pattern_member) return "pattern member";
  }
  return "clean";
}

export interface LegendEntry {
  label: string;
  colour: string;
  /** How the mark is drawn, so the swatch matches the chart rather than being a square. */
  shape: "triangle" | "dashed" | "pin" | "paint" | "band" | "cross";
}

/**
 * Named marks for the selected family — a chart legend, not a caption of dates.
 *
 * The dashed entry carries its own shape because a colour swatch cannot show a stroke dash,
 * and the absent column is the one mark a reader most needs to recognise.
 */
export function legendEntries(family: string): LegendEntry[] {
  switch (family) {
    case "gaps":
      return [
        { label: "Session-open hole", colour: "var(--diff-strip-removed)", shape: "triangle" },
        { label: "Settlement never arrived", colour: "var(--absent-mark)", shape: "dashed" },
      ];
    case "duplicates":
      return [{ label: "Kept timestamp", colour: "var(--accent-primary)", shape: "pin" }];
    case "invalid":
      return [
        { label: "Invalid value", colour: "var(--category-red)", shape: "paint" },
        { label: "Volume defect", colour: "var(--category-orange)", shape: "paint" },
      ];
    case "patterns":
      return [{ label: "Participating session", colour: "var(--category-blue)", shape: "band" }];
    default:
      return [];
  }
}

/** Whether the VWAP panel should name its breaks for this family and grain. */
export function namesVwapBreaks(
  family: string,
  vwapMeta: { name_breaks?: boolean } | undefined,
  showFamilyMarks: boolean,
): boolean {
  return (
    showFamilyMarks &&
    Boolean(vwapMeta?.name_breaks) &&
    (family === "gaps" || family === "patterns" || family === "invalid")
  );
}

/** `16:00-17:00 America/Chicago` → `16`. Null when the bucket names no hour. */
export function hourFromBucket(bucket: string): number | null {
  const text = String(bucket);
  if (!text.includes(":")) return null;
  const digits = (text.split(":")[0] ?? "").replace(/\D/g, "");
  if (!digits) return null;
  const hour = Number(digits);
  return hour >= 0 && hour <= 23 ? hour : null;
}
