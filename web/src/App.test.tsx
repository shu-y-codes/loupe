/**
 * Page assembly against a stubbed `fetch` — the tier that replaces `streamlit.testing.v1`.
 *
 * Same questions as `tests/ui/test_pages.py` asked, in the same order: given canned JSON, does
 * the page show four cards, the two charts in the right order, the VWAP refusal in place, the
 * click-through, and **no apply control anywhere**. What changed is the harness, not the
 * contract being asserted.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { checksFor, contracts, stubApi } from "./test/stub";

async function renderApp() {
  const calls = stubApi();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("heading", { name: "Loupe" });
  return { calls, user };
}

async function openReview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Review" }));
  await screen.findByRole("heading", { name: "Daily OHLCV" });
}

describe("chrome", () => {
  it("opens on Overview, because a cold session should see the corpus scan first", async () => {
    await renderApp();
    expect(await screen.findByText(/loaded contracts by grain/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("keeps the contract picker, quality grain and dates off Overview", async () => {
    const { user } = await renderApp();
    await screen.findByText(/loaded contracts by grain/i);

    expect(screen.queryByLabelText("Contract")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Quality grain" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();

    await openReview(user);
    expect(screen.getByLabelText("Contract")).toBeInTheDocument();
    expect(screen.getByLabelText("From")).toBeInTheDocument();
  });

  it("offers Quality grain on a dual-grain contract and defaults to Minute", async () => {
    const { user } = await renderApp();
    await openReview(user);

    const group = screen.getByRole("group", { name: "Quality grain" });
    expect(within(group).getByRole("button", { name: "Minute" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows a single-grain contract its held grain as context, not as a control", async () => {
    const { user } = await renderApp();
    await openReview(user);
    await user.selectOptions(screen.getByLabelText("Contract"), "SBH26");

    await waitFor(() => {
      expect(screen.queryByRole("group", { name: "Quality grain" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("Quality grain · Daily")).toBeInTheDocument();
  });

  it("names contract, month, exchange, coverage and grain in the Review header", async () => {
    const { user } = await renderApp();
    await openReview(user);

    const header = screen.getByText(/ESZ25 · December 2025 · CME/);
    expect(header).toHaveTextContent("Minute coverage: Jan 18, 2024 – Dec 19, 2025");
    expect(header).toHaveTextContent("Minute quality grain");
  });

  it("has no file uploader and no persona selector", async () => {
    const { user } = await renderApp();
    await openReview(user);

    expect(document.querySelector('input[type="file"]')).toBeNull();
    for (const label of [/persona/i, /trader/i, /analyst/i, /upload/i]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});

describe("Review main column", () => {
  it("draws four family cards, in order, as the family control", async () => {
    const { user } = await renderApp();
    await openReview(user);

    const cards = screen.getByRole("group", { name: "Check families" });
    const buttons = within(cards).getAllByRole("button");
    expect(buttons).toHaveLength(4);
    expect(buttons.map((button) => button.textContent)).toEqual([
      expect.stringContaining("Gaps"),
      expect.stringContaining("Duplicates"),
      expect.stringContaining("Invalid values"),
      expect.stringContaining("Recurring patterns"),
    ]);
    // Zero is a real answer: the check ran and found nothing.
    expect(within(cards).getByText("0 records")).toBeInTheDocument();
  });

  it("puts help on the count line, not on the family name", async () => {
    const { user } = await renderApp();
    await openReview(user);

    const count = screen.getByText("5,209 runs");
    expect(count).toHaveAttribute("title", expect.stringContaining("holes in the expected grid"));
    expect(screen.getByText(/^Gaps/)).not.toHaveAttribute("title");
  });

  it("clicking a card re-asks /dq/checks for that family and nothing else", async () => {
    const { calls, user } = await renderApp();
    await openReview(user);

    const cards = screen.getByRole("group", { name: "Check families" });
    await user.click(within(cards).getByRole("button", { name: /Duplicates/ }));

    await waitFor(() => {
      expect(calls.paths.some((path) => path.includes("family=duplicates"))).toBe(true);
    });
    expect(calls.paths.every((path) => !path.includes("/findings"))).toBe(true);
  });

  it("never puts one contract's numbers under another contract's header", async () => {
    /**
     * Found by a live pass: selecting a new contract left the previous one's cards, candles
     * and issues on screen under a header that already named the new one. The scope the
     * envelope answers is checked before it is drawn.
     */
    // The second contract's envelope never arrives, so the window between selecting it and
    // seeing its numbers is held open for the length of the assertion.
    stubApi({
      checks: (params) => {
        if (params.get("contract") === "SBH26") throw new Error("never resolves");
        return checksFor(params.get("family") ?? "gaps");
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Loupe" });
    await user.click(screen.getByRole("button", { name: "Review" }));
    expect(await screen.findByText("5,209 runs")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Contract"), "SBH26");

    await waitFor(() => {
      expect(screen.queryByText("5,209 runs")).not.toBeInTheDocument();
    });
    expect(screen.getByText(/^SBH26 · March 2026/)).toBeInTheDocument();
  });

  it("captions the picture with the family the envelope answered, not the one just clicked", async () => {
    /**
     * Also from the live pass: the heading moved on the click while the payload had not, so a
     * gaps ribbon sat under "Picture of invalid values". The envelope names its own family.
     */
    stubApi({
      // The server answers every request with a gaps envelope, whatever was asked for.
      checks: () => checksFor("gaps"),
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Loupe" });
    await user.click(screen.getByRole("button", { name: "Review" }));
    const cards = await screen.findByRole("group", { name: "Check families" });

    await user.click(within(cards).getByRole("button", { name: /Invalid values/ }));
    await waitFor(() => {
      expect(
        within(cards).getByRole("button", { name: /Invalid values/ }),
      ).toHaveAttribute("aria-pressed", "true");
    });

    // The card selection is optimistic; the picture and its caption stay together.
    expect(screen.getByRole("heading", { name: "Picture of gaps" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Issues in selected family · Gaps" }),
    ).toBeInTheDocument();
  });

  it("keeps the order cards → OHLCV → VWAP → picture → issues", async () => {
    const { user } = await renderApp();
    await openReview(user);

    const headings = within(screen.getByRole("main"))
      .getAllByRole("heading", { level: 2 })
      .map((node) => node.textContent);
    expect(headings).toEqual([
      "Daily OHLCV",
      "Rolling 15-minute VWAP",
      "Picture of gaps",
      "Issues in selected family · Gaps",
    ]);
  });

  it("names the bar source and the resolved grain under Daily OHLCV", async () => {
    const { user } = await renderApp();
    await openReview(user);
    expect(
      screen.getByText(/Derived from minute · Minute quality grain · selected family/),
    ).toBeInTheDocument();
  });

  it("reads the four routes the spec names, and never /dq/findings", async () => {
    const { calls, user } = await renderApp();
    await openReview(user);

    expect(calls.paths.some((path) => path.startsWith("/v1/dq/checks"))).toBe(true);
    expect(calls.paths.some((path) => path.startsWith("/v1/analytics/bars/daily"))).toBe(true);
    expect(calls.paths.some((path) => path.startsWith("/v1/analytics/vwap"))).toBe(true);
    expect(calls.paths.some((path) => path.startsWith("/v1/health"))).toBe(true);
    expect(calls.paths.some((path) => path.includes("/dq/findings"))).toBe(false);
    expect(calls.paths.some((path) => path.includes("/dq/summary"))).toBe(false);
  });

  it("draws no score line", async () => {
    const { user } = await renderApp();
    await openReview(user);
    // `score` and `scope_signature` arrive on the envelope; this page does not draw them.
    expect(screen.queryByText(/91\.4/)).not.toBeInTheDocument();
    expect(screen.queryByText(/scope_signature|cmp\+unq/)).not.toBeInTheDocument();
  });

  it("has no apply, override, dismiss or resolve control", async () => {
    const { user } = await renderApp();
    await openReview(user);

    for (const label of [/^apply/i, /override/i, /dismiss/i, /accept/i, /resolve/i, /edit/i]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });

  it("says validation has not finished rather than drawing empty charts", async () => {
    stubApi({ checks: () => checksFor("gaps", { checked: false }) });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Loupe" });
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(
      await screen.findByText(/Validation has not finished for this contract yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Daily OHLCV" })).not.toBeInTheDocument();
  });
});

describe("VWAP panel", () => {
  it("keeps the panel and says it needs minute bars when the API refuses", async () => {
    stubApi({
      vwapProblem: {
        status: 422,
        code: "CAP.FREQUENCY_UNAVAILABLE",
        title: "Frequency unavailable",
        detail: "SBH26 holds no minute records, so a 15-minute VWAP cannot be computed.",
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Loupe" });
    await user.click(screen.getByRole("button", { name: "Review" }));
    await screen.findByRole("heading", { name: "Rolling 15-minute VWAP" });

    expect(screen.getByText("Needs minute bars")).toBeInTheDocument();
    expect(screen.getByText(/holds no minute records/)).toBeInTheDocument();
  });

  it("labels the line context-only at Daily quality grain and drops the family marks", async () => {
    stubApi({
      checks: (params) =>
        checksFor(params.get("family") ?? "gaps", {
          scope: {
            contracts: ["ESZ25"],
            start: null,
            end: null,
            basis: "clean",
            frequency: "daily",
            frequency_defaulted: false,
          },
        }),
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Loupe" });
    await user.click(screen.getByRole("button", { name: "Review" }));
    await screen.findByRole("heading", { name: "Rolling 15-minute VWAP" });

    expect(
      screen.getByText("Minute tape · context only for Daily quality grain"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Crosses name a break/)).not.toBeInTheDocument();
  });
});

describe("Overview", () => {
  it("lists one row per contract × held grain, with headline counts only", async () => {
    await renderApp();
    const table = await screen.findByRole("table");

    // ESZ25 holds both grains, so it appears twice; SBH26 is daily-only.
    expect(within(table).getAllByText("ESZ25")).toHaveLength(2);
    // Three rows: ESZ25 minute, ESZ25 daily, SBH26 daily.
    expect(within(table).getAllByText("5,209 runs")).toHaveLength(3);
    // Detail stays on Review.
    expect(within(table).queryByText(/session-open holes ·/)).not.toBeInTheDocument();
  });

  it("puts family meaning on the column header, where the help belongs", async () => {
    await renderApp();
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Gaps" })).toHaveAttribute(
      "title",
      expect.stringContaining("holes in the expected grid"),
    );
  });

  it("filters by grain without touching Quality grain", async () => {
    const { user } = await renderApp();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Daily" }));
    await waitFor(() => {
      expect(screen.getAllByRole("row")).toHaveLength(3); // header + two daily rows
    });
  });

  it("opens Review on the clicked contract and grain, leaving family as it was", async () => {
    const { user } = await renderApp();
    const table = await screen.findByRole("table");

    // Select a non-default family first, so "family is left alone" is actually observable.
    await user.click(screen.getByRole("button", { name: "Review" }));
    const cards = await screen.findByRole("group", { name: "Check families" });
    await user.click(within(cards).getByRole("button", { name: /Invalid values/ }));
    await user.click(screen.getByRole("button", { name: "Overview" }));

    await user.click(
      await screen.findByRole("button", { name: "Open ESZ25 minute in Review" }),
    );

    await screen.findByRole("heading", { name: "Daily OHLCV" });
    expect(screen.getByLabelText("Contract")).toHaveValue("ESZ25");
    expect(
      within(screen.getByRole("group", { name: "Check families" })).getByRole("button", {
        name: /Invalid values/,
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(table).not.toBeInTheDocument();
  });

  it("does not re-hit /dq/checks per contract just because you came back", async () => {
    // Overview costs one request per contract × grain — 48 on the sample corpus. Paying that
    // again for a round trip through Review is the loop the spec says to cache.
    const { calls, user } = await renderApp();
    await screen.findByRole("table");
    const first = calls.paths.filter((path) => path.startsWith("/v1/dq/checks")).length;
    expect(first).toBe(3);

    await user.click(screen.getByRole("button", { name: "Review" }));
    await screen.findByRole("heading", { name: "Daily OHLCV" });
    const afterReview = calls.paths.filter((path) => path.startsWith("/v1/dq/checks")).length;

    await user.click(screen.getByRole("button", { name: "Overview" }));
    await screen.findByRole("table");
    expect(
      calls.paths.filter((path) => path.startsWith("/v1/dq/checks")).length,
    ).toBe(afterReview);
  });

  it("says the check has not run rather than painting a zero as clean", async () => {
    stubApi({ checks: () => checksFor("gaps", { checked: false }) });
    render(<App />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("Check has not run").length).toBeGreaterThan(0);
  });

  it("invites Load demo data on an empty store, and never an uploader", async () => {
    stubApi({
      contracts: [],
      health: { records: 0, contracts: 0, batches: 0 },
    });
    render(<App />);
    expect(
      await screen.findByText(/No contracts loaded yet\. Load demo data from the sidebar/),
    ).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });
});

describe("failure states", () => {
  it("says the API did not answer, in place, without inviting an uploader", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("failed to fetch"))));
    render(<App />);

    expect(await screen.findByText("The API did not answer")).toBeInTheDocument();
    expect(screen.getByText(/Is the API running\?/)).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("names the bootstrap command when the store has no schema", async () => {
    stubApi({ health: { schema_applied: false, rules_seeded: false, records: 0 } });
    render(<App />);
    expect(await screen.findByText("The store has no schema yet")).toBeInTheDocument();
    expect(
      screen.getByText("uv run uvicorn loupe.api.app:bootstrapped_app --factory"),
    ).toBeInTheDocument();
  });

  it("says the rule catalogue is not seeded when rules are missing", async () => {
    stubApi({ health: { rules_seeded: false } });
    render(<App />);
    expect(await screen.findByText("The rule catalogue is not seeded")).toBeInTheDocument();
  });

  it("says a contract reporting no held grain cannot be reviewed", async () => {
    stubApi({
      contracts: [{ ...contracts[0]!, frequencies_available: [], coverage: {} }],
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Loupe" });
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(
      await screen.findByText(/does not report a held quality grain/),
    ).toBeInTheDocument();
  });
});
