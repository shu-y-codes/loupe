/**
 * The marks themselves, drawn.
 *
 * These are the assertions the Streamlit suite could only make against a Vega spec. The
 * grammar is now SVG, so the tests read the SVG: an absent settlement is a dashed labelled
 * column and **never** a rect at zero, paint is for `invalid` alone, and the legend names the
 * selected family's marks.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Ohlcv } from "./Ohlcv";
import type { Slot } from "./overlay";

const slot = (trade_date: string, overrides: Partial<Slot> = {}): Slot => ({
  trade_date,
  open: 6010,
  high: 6018,
  low: 6005,
  close: 6014,
  volume: 142000,
  session: "present",
  partial_gap: false,
  duplicate: false,
  invalid: false,
  invalid_volume: false,
  pattern_member: false,
  caption: "",
  ...overrides,
});

const absent = (trade_date: string): Slot =>
  slot(trade_date, {
    open: null,
    high: null,
    low: null,
    close: null,
    volume: null,
    session: "absent",
  });

function draw(slots: Slot[], family: string) {
  const { container } = render(<Ohlcv slots={slots} family={family} scopeKey="k" />);
  return container;
}

/**
 * The price pane alone.
 *
 * The legend draws its swatches as SVG too — a triangle for a hole, a circle for a pin — so a
 * query over the whole container would count the key as if it were a mark on the chart.
 */
function price(container: HTMLElement): SVGSVGElement {
  return container.querySelectorAll("svg")[0] as SVGSVGElement;
}

function volume(container: HTMLElement): SVGSVGElement {
  return container.querySelectorAll("svg")[1] as SVGSVGElement;
}

describe("absent settlements", () => {
  const slots = [slot("2025-06-02"), absent("2025-06-16"), slot("2025-06-17")];

  it("are a dashed column with an on-chart label, not a bar", () => {
    const container = draw(slots, "gaps");
    expect(price(container).querySelectorAll("line[stroke-dasharray]")).toHaveLength(1);
    expect(price(container).textContent).toContain("absent");
  });

  it("never draw a zero-filled candle body", () => {
    const container = draw(slots, "gaps");
    // Every rect in the price pane is a candle body; two priced sessions means two of them,
    // and the absent day contributes none rather than a zero-height one.
    const bodies = [...price(container).querySelectorAll("rect")];
    expect(bodies).toHaveLength(2);
    expect(bodies.every((rect) => Number(rect.getAttribute("height")) > 0)).toBe(true);
    expect(volume(container).querySelectorAll("rect")).toHaveLength(2);
  });

  it("stay a quiet column when the selected family is not gaps or patterns", () => {
    const container = draw(slots, "duplicates");
    expect(price(container).textContent).not.toContain("absent");
    expect(price(container).querySelectorAll("line[stroke-dasharray]")).toHaveLength(1);
  });
});

describe("family marks", () => {
  it("puts a triangle on a session-open hole and leaves the body the clean series", () => {
    const container = draw([slot("2025-06-02", { partial_gap: true })], "gaps");
    expect(price(container).querySelectorAll("polygon")).toHaveLength(1);
    const body = price(container).querySelector("rect");
    // The defect is missing time, not a bad close, so the candle keeps the neutral colour.
    expect(body?.getAttribute("fill")).toBe("var(--neutral-mark)");
  });

  it("pins a kept duplicate without recolouring the body", () => {
    const container = draw([slot("2025-06-18", { duplicate: true })], "duplicates");
    expect(price(container).querySelectorAll("circle")).toHaveLength(1);
    expect(price(container).querySelector("rect")?.getAttribute("fill")).toBe(
      "var(--neutral-mark)",
    );
  });

  it("paints the candle for an invalid value — the one family where painting works", () => {
    const container = draw([slot("2025-06-20", { invalid: true })], "invalid");
    expect(price(container).querySelector("rect")?.getAttribute("fill")).toBe(
      "var(--category-red)",
    );
  });

  it("puts a volume defect on the volume pane, not the wick", () => {
    const container = draw([slot("2025-06-09", { invalid_volume: true })], "invalid");
    expect(volume(container).querySelector("rect")?.getAttribute("fill")).toBe(
      "var(--category-orange)",
    );
    // The price body stays neutral: the volume is the broken field, not the close.
    expect(price(container).querySelector("rect")?.getAttribute("fill")).toBe(
      "var(--neutral-mark)",
    );
  });

  it("bands every participating session for patterns", () => {
    const container = draw(
      [slot("2025-06-02", { pattern_member: true }), slot("2025-06-03")],
      "patterns",
    );
    const bands = [...price(container).querySelectorAll("rect")].filter(
      (rect) => rect.getAttribute("opacity") === "0.12",
    );
    expect(bands).toHaveLength(1);
  });

  it("ignores max_severity — a defect in another family draws nothing", () => {
    const container = draw([slot("2025-06-20", { invalid: true })], "gaps");
    expect(price(container).querySelector("rect")?.getAttribute("fill")).toBe(
      "var(--neutral-mark)",
    );
    expect(price(container).querySelectorAll("polygon")).toHaveLength(0);
  });
});

describe("legend and hover", () => {
  it("names the selected family's marks", () => {
    const container = draw([slot("2025-06-02", { partial_gap: true })], "gaps");
    expect(container.textContent).toContain("Session-open hole");
    expect(container.textContent).toContain("Settlement never arrived");
  });

  it("changes the legend with the family", () => {
    const container = draw([slot("2025-06-02", { duplicate: true })], "duplicates");
    expect(container.textContent).toContain("Kept timestamp");
    expect(container.textContent).not.toContain("Session-open hole");
  });

  it("hovers date, OHLC and status — never a colour-encoding field name", () => {
    const container = draw([slot("2025-06-02", { partial_gap: true })], "gaps");
    const titles = [...container.querySelectorAll("title")].map((node) => node.textContent);
    expect(titles[0]).toContain("2025-06-02");
    expect(titles[0]).toContain("gap: session-open hole");
    expect(titles.join(" ")).not.toContain("fill");
  });

  it("hovers volume with a status and no encoding noise", () => {
    const container = draw([slot("2025-06-09", { invalid_volume: true })], "invalid");
    const titles = [...container.querySelectorAll("title")].map((node) => node.textContent);
    expect(titles.some((title) => title?.includes("volume 142,000"))).toBe(true);
    expect(titles.some((title) => title?.includes("volume defect"))).toBe(true);
  });

  it("says a holiday is a holiday, not an absent settlement", () => {
    const container = draw(
      [slot("2025-06-19", { session: "holiday", open: null, high: null, low: null, close: null })],
      "gaps",
    );
    const labels = [...price(container).querySelectorAll("text")].map((node) => node.textContent);
    expect(labels).toContain("hol");
    expect(labels).not.toContain("absent");
    expect(price(container).querySelectorAll("line[stroke-dasharray]")).toHaveLength(0);
  });

  it("says so plainly when there are no bars", () => {
    const { container } = render(<Ohlcv slots={[]} family="gaps" scopeKey="k" />);
    expect(container.textContent).toContain("No bars in this window.");
  });

  it("tells the reader how to reset the zoom", () => {
    const container = draw([slot("2025-06-02")], "gaps");
    expect(container.textContent).toContain("Double-click to reset");
  });
});
