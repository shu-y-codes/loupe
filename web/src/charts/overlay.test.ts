/**
 * The overlay join and the status vocabulary — the half of the charts that has rules.
 *
 * Replaces `tests/ui/test_charts.py`. The drawing itself is asserted where it matters (the
 * absent column, the legend, the break) in `Ohlcv.test.tsx`; this file covers the data shape
 * those marks are derived from.
 */

import { describe, expect, it } from "vitest";
import type { Bar, OverlayMark } from "../api/types";
import { hourFromBucket, legendEntries, namesVwapBreaks, overlaySlots, overlayStatus } from "./overlay";
import { bucketSeries, chartScopeKey, clampExtent, extremes, zoomExtent } from "./scale";

const bar = (trade_date: string, overrides: Partial<Bar> = {}): Bar => ({
  contract_id: "ESZ25",
  trade_date,
  open: 6010,
  high: 6018,
  low: 6005,
  close: 6014,
  volume: 142000,
  record_count: 1380,
  expected_count: 1380,
  completeness_pct: 100,
  finding_count: 0,
  max_severity: null,
  ...overrides,
});

const mark = (trade_date: string, overrides: Partial<OverlayMark> = {}): OverlayMark => ({
  trade_date,
  session: "present",
  partial_gap: false,
  duplicate: false,
  invalid: false,
  invalid_volume: false,
  pattern_member: false,
  caption: "",
  ...overrides,
});

describe("overlaySlots", () => {
  it("joins marks to bars by trade_date", () => {
    const slots = overlaySlots(
      [bar("2025-06-02"), bar("2025-06-03")],
      [mark("2025-06-03", { partial_gap: true })],
    );
    expect(slots.map((slot) => slot.partial_gap)).toEqual([false, true]);
  });

  it("keeps a mark that has no bar, with no OHLC — never a zero-filled candle", () => {
    const slots = overlaySlots(
      [bar("2025-06-02")],
      [mark("2025-06-16", { session: "absent", caption: "Settlement never arrived" })],
    );
    const absent = slots.find((slot) => slot.trade_date === "2025-06-16");

    expect(absent).toBeDefined();
    expect(absent?.session).toBe("absent");
    expect(absent?.open).toBeNull();
    expect(absent?.close).toBeNull();
    expect(absent?.volume).toBeNull();
  });

  it("returns slots in date order whichever side contributed them", () => {
    const slots = overlaySlots(
      [bar("2025-06-20"), bar("2025-06-02")],
      [mark("2025-06-16", { session: "absent" })],
    );
    expect(slots.map((slot) => slot.trade_date)).toEqual([
      "2025-06-02",
      "2025-06-16",
      "2025-06-20",
    ]);
  });

  it("tolerates a timestamped trade_date by reading only the date part", () => {
    const slots = overlaySlots(
      [bar("2025-06-02T00:00:00Z")],
      [mark("2025-06-02", { duplicate: true })],
    );
    expect(slots).toHaveLength(1);
    expect(slots[0]?.duplicate).toBe(true);
  });
});

describe("overlayStatus", () => {
  const slot = overlaySlots([bar("2025-06-02")], [])[0]!;

  it("is keyed on the selected family, not on severity", () => {
    const gapped = { ...slot, partial_gap: true, invalid: true };
    expect(overlayStatus("gaps", gapped)).toBe("gap: session-open hole");
    expect(overlayStatus("invalid", gapped)).toBe("invalid value");
    // A defect in another family is clean *for this overlay*, which is the whole point.
    expect(overlayStatus("duplicates", gapped)).toBe("clean");
  });

  it("names an absent session distinctly from a session-open hole", () => {
    expect(overlayStatus("gaps", { ...slot, session: "absent" })).toBe("gap: session missing");
  });

  it("separates a volume defect from an invalid price", () => {
    expect(overlayStatus("invalid", { ...slot, invalid_volume: true })).toBe("volume defect");
    expect(
      overlayStatus("invalid", { ...slot, invalid_volume: true, invalid: true }),
    ).toBe("invalid value");
  });

  it("says clean when nothing in the selected family applies", () => {
    expect(overlayStatus("patterns", slot)).toBe("clean");
  });
});

describe("legend", () => {
  it("names the selected family's marks and gives absent its own dashed shape", () => {
    const gaps = legendEntries("gaps");
    expect(gaps.map((entry) => entry.label)).toEqual([
      "Session-open hole",
      "Settlement never arrived",
    ]);
    expect(gaps[1]?.shape).toBe("dashed");
  });

  it("gives duplicates one entry and never recolours the body", () => {
    expect(legendEntries("duplicates")).toEqual([
      expect.objectContaining({ label: "Kept timestamp", shape: "pin" }),
    ]);
  });
});

describe("VWAP break naming", () => {
  it("names breaks for gaps, patterns and invalid when the envelope says so", () => {
    for (const family of ["gaps", "patterns", "invalid"]) {
      expect(namesVwapBreaks(family, { name_breaks: true }, true)).toBe(true);
    }
    expect(namesVwapBreaks("duplicates", { name_breaks: true }, true)).toBe(false);
  });

  it("stays silent when the grain suppresses family marks", () => {
    expect(namesVwapBreaks("gaps", { name_breaks: true }, false)).toBe(false);
  });

  it("stays silent when the envelope did not say the breaks are nameable", () => {
    expect(namesVwapBreaks("gaps", {}, true)).toBe(false);
  });
});

describe("hourFromBucket", () => {
  it("reads the leading hour off a bucket label", () => {
    expect(hourFromBucket("16:00-17:00 America/Chicago")).toBe(16);
    expect(hourFromBucket("02:30-11:59")).toBe(2);
  });

  it("returns null for a bucket that names no hour", () => {
    expect(hourFromBucket("Monday")).toBeNull();
    expect(hourFromBucket("")).toBeNull();
  });
});

describe("chart identity", () => {
  const rows = [{ trade_date: "2025-06-02" }, { trade_date: "2025-06-30" }];

  it("is unchanged by a family switch, so a family click keeps the zoom", () => {
    const scope = { contract: "ESZ25", frequency: "minute", start: null, end: null };
    expect(chartScopeKey(scope, rows, "trade_date")).toBe(
      chartScopeKey({ ...scope }, rows, "trade_date"),
    );
  });

  it("changes with contract, grain and dates, so those reset the zoom", () => {
    const base = { contract: "ESZ25", frequency: "minute", start: null, end: null };
    const key = chartScopeKey(base, rows, "trade_date");
    expect(chartScopeKey({ ...base, contract: "ZNZ25" }, rows, "trade_date")).not.toBe(key);
    expect(chartScopeKey({ ...base, frequency: "daily" }, rows, "trade_date")).not.toBe(key);
    expect(chartScopeKey({ ...base, start: "2025-06-01" }, rows, "trade_date")).not.toBe(key);
  });

  it("changes when the returned extent changes even if the scope object matches", () => {
    const scope = { contract: "ESZ25", frequency: "minute", start: null, end: null };
    expect(chartScopeKey(scope, rows, "trade_date")).not.toBe(
      chartScopeKey(scope, [{ trade_date: "2025-07-01" }], "trade_date"),
    );
  });
});

describe("zoom arithmetic", () => {
  it("never lets the window leave the data", () => {
    expect(clampExtent({ start: -5, end: 4 }, 10)).toEqual({ start: 0, end: 9 });
    expect(clampExtent({ start: 8, end: 20 }, 10)).toEqual({ start: 0, end: 10 });
  });

  it("never collapses below a readable number of slots", () => {
    expect(clampExtent({ start: 4, end: 4 }, 10).end).toBeGreaterThan(4);
  });

  it("zooms around the pointer rather than the middle", () => {
    const zoomed = zoomExtent({ start: 0, end: 20 }, 20, 0.5, 0);
    expect(zoomed.start).toBe(0);
    expect(zoomed.end).toBe(10);
  });
});


describe("series at real size", () => {
  /**
   * A live pass against the sample corpus asked `/v1/analytics/vwap` for ESZ25 and got
   * **114,477 points**. `Math.max(...values)` on that many arguments is a stack overflow, and
   * the page died on `RangeError` before it drew anything. These are the regressions.
   */
  const HUGE = 114_477;

  it("finds extremes on a hundred thousand points without spreading them into a call", () => {
    const values = Array.from({ length: HUGE }, (_, index) => index % 5000);
    expect(extremes(values)).toEqual({ min: 0, max: 4999 });
    expect(() => Math.max(...values)).toThrow(RangeError);
  });

  it("reports nothing to bound for an all-null series rather than a fake range", () => {
    expect(extremes([])).toBeNull();
    expect(extremes([NaN, Infinity])).toBeNull();
  });

  it("caps how many marks are drawn without changing any value", () => {
    const points = Array.from({ length: HUGE }, (_, index) => ({ v: index }));
    const marks = bucketSeries(points, 720, (point) => point.v);

    expect(marks).toHaveLength(720);
    // Every value drawn is a value that is in the series — a selection, never an average.
    expect(marks.every((mark) => Number.isInteger(mark.value))).toBe(true);
    expect(marks[0]?.value).toBe(0);
  });

  it("leaves a short series alone", () => {
    const points = [{ v: 1 }, { v: null }, { v: 3 }];
    const marks = bucketSeries(points, 720, (point) => point.v);
    expect(marks.map((mark) => mark.value)).toEqual([1, null, 3]);
    expect(marks.map((mark) => mark.broken)).toEqual([false, true, false]);
  });

  it("never hides a break: a bucket holding any null is a break", () => {
    // One null in a thousand points. Under-reporting it would draw a connected line across a
    // window whose volume was dropped — the one thing the semantics forbid.
    const points = Array.from({ length: 1000 }, (_, index) => ({
      v: index === 500 ? null : index,
    }));
    const marks = bucketSeries(points, 10, (point) => point.v);
    expect(marks.filter((mark) => mark.broken)).toHaveLength(1);
  });
});
