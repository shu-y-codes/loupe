/**
 * The demo panel: consent, the two separate buttons, and the grouping rules.
 *
 * Replaces `tests/ui/test_demo_panel.py`. The grouping functions are asserted directly because
 * they are the part with rules — coverage is a fact about the *contract*, not about the file's
 * own frequency, and the CSV mark is keyed on `origin = demo` rather than on "any CSV".
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BatchSummary, Contract } from "../api/types";
import { DemoPanel, groupBatchesByCoverage, isDemoCsvConversion } from "./DemoPanel";
import { batches, contracts, health, stubApi } from "../test/stub";

const batch = (overrides: Partial<BatchSummary>): BatchSummary => ({
  batch_id: "b",
  status: "loaded",
  filename: "f.parquet",
  file_format: "parquet",
  origin: "demo",
  frequency: "daily",
  rows_accepted: 10,
  contracts_detected: [],
  ...overrides,
});

const contract = (id: string, grains: string[]): Contract => ({
  contract_id: id,
  root: id.slice(0, 2),
  exchange: "CME",
  contract_month: null,
  tick_size: null,
  multiplier: null,
  coverage: {},
  frequencies_available: grains,
  roll_date: null,
  dates_inferred: true,
});

describe("coverage grouping", () => {
  it("files a dual-grain contract's daily file under Daily + minute, not Daily-only", () => {
    const groups = groupBatchesByCoverage(
      [
        batch({ batch_id: "1", filename: "ESZ25_daily.csv", contracts_detected: ["ESZ25"] }),
        batch({
          batch_id: "2",
          filename: "ESZ25.parquet",
          frequency: "minute",
          contracts_detected: ["ESZ25"],
        }),
      ],
      [contract("ESZ25", ["daily", "minute"])],
    );
    expect(groups).toHaveLength(1);
    expect(groups[0]?.[0]).toBe("Daily + minute");
    expect(groups[0]?.[1]).toHaveLength(2);
  });

  it("separates daily-only and minute-only contracts", () => {
    const groups = groupBatchesByCoverage(
      [
        batch({ batch_id: "1", contracts_detected: ["SBH26"] }),
        batch({
          batch_id: "2",
          frequency: "minute",
          contracts_detected: ["GCH26"],
        }),
      ],
      [contract("SBH26", ["daily"]), contract("GCH26", ["minute"])],
    );
    expect(groups.map(([label]) => label)).toEqual(["Daily-only", "Minute-only"]);
  });

  it("falls back to the batch's own frequency when the contract list is empty", () => {
    const groups = groupBatchesByCoverage(
      [batch({ batch_id: "1", contracts_detected: ["NEW26"] })],
      [],
    );
    expect(groups.map(([label]) => label)).toEqual(["Daily-only"]);
  });

  it("lists a batch once even when it spans several contracts", () => {
    const groups = groupBatchesByCoverage(
      [batch({ batch_id: "1", contracts_detected: ["A", "B"] })],
      [contract("A", ["daily"]), contract("B", ["daily"])],
    );
    expect(groups.flatMap(([, rows]) => rows)).toHaveLength(1);
  });
});

describe("the CSV conversion mark", () => {
  it("marks a demo CSV, because that is the CSV half of 'accept CSV or Parquet'", () => {
    expect(isDemoCsvConversion(batch({ filename: "a.csv", file_format: "csv" }))).toBe(true);
  });

  it("does not mark an injected CSV — that mark is the synthetic disclosure", () => {
    expect(
      isDemoCsvConversion(batch({ filename: "a.csv", file_format: "csv", origin: "injected" })),
    ).toBe(false);
  });

  it("does not mark any CSV a person happened to upload", () => {
    expect(
      isDemoCsvConversion(batch({ filename: "a.csv", file_format: "csv", origin: "upload" })),
    ).toBe(false);
  });

  it("does not mark a demo Parquet", () => {
    expect(isDemoCsvConversion(batch({ filename: "a.parquet" }))).toBe(false);
  });
});

describe("the panel", () => {
  const noop = () => undefined;

  it("says what it will download, and from where, before the button", async () => {
    stubApi();
    render(
      <DemoPanel health={{ ...health, records: 0 }} contracts={[]} onChanged={noop} />,
    );

    expect(await screen.findByText(/Load ~16 MB of real futures data/)).toBeInTheDocument();
    const disclosure = screen.getByText("What this downloads");
    expect(disclosure).toBeInTheDocument();
    expect(screen.getByText("lynx1231/historical-futures-data-sample")).toBeInTheDocument();
    expect(screen.getByText("29efdfa21c5a")).toBeInTheDocument();
    expect(screen.getByText(/nothing authorises redistribution/)).toBeInTheDocument();
  });

  it("offers Load demo data on an empty store and nothing else", async () => {
    stubApi();
    render(
      <DemoPanel health={{ ...health, records: 0 }} contracts={[]} onChanged={noop} />,
    );
    await screen.findByRole("button", { name: "Load demo data" });
    expect(screen.queryByRole("button", { name: /Inject/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
  });

  it("offers Inject separately once real data is loaded, and says what it plants", async () => {
    stubApi();
    render(<DemoPanel health={health} contracts={contracts} onChanged={noop} />);

    expect(await screen.findByRole("button", { name: "Inject demo defects" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load demo data" })).not.toBeInTheDocument();
    expect(screen.getByText(/Every finding above is real/)).toBeInTheDocument();
    expect(screen.getByText(/The vendor files on disk are never modified/)).toBeInTheDocument();
  });

  it("swaps Inject for Remove once defects are planted, with the count and the groups", async () => {
    stubApi();
    render(
      <DemoPanel
        health={{ ...health, synthetic_batches: 1, synthetic_records: 346 }}
        contracts={contracts}
        onChanged={noop}
      />,
    );

    expect(await screen.findByRole("button", { name: "Remove demo defects" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Inject demo defects" })).not.toBeInTheDocument();
    expect(screen.getByText("346 synthetic records")).toBeInTheDocument();

    // Grouped by strip family, filename nested, and no "findings below" sentence.
    expect(await screen.findByText("Invalid values")).toBeInTheDocument();
    expect(screen.getByText("Other (off the strip)")).toBeInTheDocument();
    expect(screen.getAllByText("SR3G26_with_defects.csv").length).toBeGreaterThan(0);
    expect(screen.queryByText(/findings below/i)).not.toBeInTheDocument();
  });

  it("uses a warning callout rather than an emoji for the synthetic mark", async () => {
    stubApi();
    const { container } = render(
      <DemoPanel
        health={{ ...health, synthetic_batches: 1, synthetic_records: 346 }}
        contracts={contracts}
        onChanged={noop}
      />,
    );
    await screen.findByRole("button", { name: "Remove demo defects" });
    expect(container.textContent).not.toContain("⚠️");
  });

  it("renders the progress the route streams, ending on the finished result", async () => {
    stubApi({
      demoEvents: [
        { event: "started", message: "Fetching the sample corpus…", phase: "fetch" },
        {
          event: "progress",
          message: "Fetching 3/48 · ESZ25.parquet",
          phase: "fetch",
          done: 3,
          total: 48,
        },
        { event: "done", message: "Loaded 48 files (46 Parquet, 2 CSV)", loaded: 48 },
      ],
    });
    const user = userEvent.setup();
    render(
      <DemoPanel health={{ ...health, records: 0 }} contracts={[]} onChanged={noop} />,
    );

    await user.click(await screen.findByRole("button", { name: "Load demo data" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Loaded 48 files (46 Parquet, 2 CSV)",
      );
    });
  });

  it("answers a failed fetch in place, with the hint, and never points at an uploader", async () => {
    stubApi({
      demoEvents: [
        {
          event: "error",
          title: "Could not fetch the corpus",
          message: "No route to huggingface.co.",
          hint: "The app is fully usable without the sample corpus.",
        },
      ],
    });
    const user = userEvent.setup();
    render(
      <DemoPanel health={{ ...health, records: 0 }} contracts={[]} onChanged={noop} />,
    );

    await user.click(await screen.findByRole("button", { name: "Load demo data" }));
    expect(await screen.findByText("Could not fetch the corpus")).toBeInTheDocument();
    expect(screen.getByText(/fully usable without the sample corpus/)).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("surfaces a checksum warning without treating it as a failure", async () => {
    stubApi({
      demoEvents: [
        { event: "warning", message: "Checksum mismatch on ESZ25.parquet; it was fetched but does not verify." },
        { event: "done", message: "Loaded 48 files", loaded: 48 },
      ],
    });
    const user = userEvent.setup();
    render(
      <DemoPanel health={{ ...health, records: 0 }} contracts={[]} onChanged={noop} />,
    );

    await user.click(await screen.findByRole("button", { name: "Load demo data" }));
    expect(await screen.findByText(/does not verify/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loaded 48 files");
  });

  it("lists what the store holds, grouped, with the conversion mark", async () => {
    stubApi();
    const user = userEvent.setup();
    render(<DemoPanel health={health} contracts={contracts} onChanged={noop} />);

    const summary = await screen.findByText(`${batches.data.length} ingested files`);
    await user.click(summary);
    const list = summary.closest("details")!;
    expect(within(list).getByText("Daily + minute")).toBeInTheDocument();
    // The line is `<code>name</code> · format · origin · mark`, so it is several nodes.
    expect(list.textContent).toContain("daily.csv · csv · demo · Converted from Parquet");
    expect(list.textContent).toContain("ESZ25.parquet · parquet · demo");
    expect(
      within(list).getByText("What this store holds — not a directory of downloads."),
    ).toBeInTheDocument();
  });
});
