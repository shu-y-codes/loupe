/**
 * The stubbed API the page tests run against — this tier's whole seam.
 *
 * It replaces `tests/ui/ui_helpers.py`'s `FakeClient`. Same job, same reason: these are view
 * assembly tests, and a page test that needed a database would be re-testing `quality`, while
 * one that needed a live server could not run in CI at all.
 *
 * **Every key here is checked against the real OpenAPI document** (`src/api/schema.test.ts`).
 * That check is the point. A stub is a place to invent a field the API does not have, and a
 * page that reads the invented field passes its own test forever — the parity guard is what
 * catches it, and it is why the Streamlit suite had one too.
 */

import { vi } from "vitest";
import type {
  BarsResponse,
  BatchesResponse,
  ChecksResponse,
  Contract,
  CorpusDescription,
  Health,
  InjectionResponse,
  VwapResponse,
} from "../api/types";

export const health: Health = {
  status: "ok",
  schema_applied: true,
  rules_seeded: true,
  records: 114477,
  contracts: 2,
  batches: 3,
  synthetic_batches: 0,
  synthetic_records: 0,
};

export const contracts: Contract[] = [
  {
    contract_id: "ESZ25",
    root: "ES",
    exchange: "CME",
    contract_month: "2025-12",
    tick_size: 0.25,
    multiplier: 50,
    coverage: {
      minute: {
        first_trade_date: "2024-01-18",
        last_trade_date: "2025-12-19",
        sessions: 224,
        records: 114477,
      },
      daily: {
        first_trade_date: "2021-03-22",
        last_trade_date: "2025-12-19",
        sessions: 1145,
        records: 1145,
      },
    },
    frequencies_available: ["daily", "minute"],
    roll_date: null,
    dates_inferred: true,
  },
  {
    contract_id: "SBH26",
    root: "SB",
    exchange: "ICEUS",
    contract_month: "2026-03",
    tick_size: 0.01,
    multiplier: 1120,
    coverage: {
      daily: {
        first_trade_date: "2023-03-01",
        last_trade_date: "2026-02-27",
        sessions: 731,
        records: 731,
      },
    },
    frequencies_available: ["daily"],
    roll_date: null,
    dates_inferred: true,
  },
];

export function checksFor(family = "gaps", overrides: Partial<ChecksResponse> = {}): ChecksResponse {
  return {
    scope: {
      contracts: ["ESZ25"],
      start: null,
      end: null,
      basis: "clean",
      frequency: "minute",
      frequency_defaulted: false,
    },
    contract_id: "ESZ25",
    score: 91.4,
    scope_signature: "cmp+unq+val+con",
    dimensions_not_in_scope: [],
    frequencies: ["daily", "minute"],
    checked: true,
    families: [
      {
        family: "gaps",
        label: "Gaps",
        count: 5209,
        unit: "runs",
        detail: "5209 session-open holes · 2 sessions absent",
      },
      {
        family: "duplicates",
        label: "Duplicates",
        count: 0,
        unit: "records",
        detail: "0 exact copies · 0 key conflicts",
      },
      {
        family: "invalid",
        label: "Invalid values",
        count: 1,
        unit: "rows",
        detail: "0 prices · 1 volume",
      },
      {
        family: "patterns",
        label: "Recurring patterns",
        count: 74,
        unit: "standing",
        detail: "Open-hour gaps, 44 of 44 sessions",
      },
    ],
    issues: [
      {
        family,
        what: "Session-open holes",
        days: 18,
        records: 72,
        what_we_did: "excluded 4 open slots",
      },
    ],
    overlay: {
      family,
      ohlcv: [
        {
          trade_date: "2025-06-02",
          session: "present",
          partial_gap: true,
          duplicate: false,
          invalid: false,
          invalid_volume: false,
          pattern_member: true,
          caption: "",
        },
        {
          trade_date: "2025-06-16",
          session: "absent",
          partial_gap: false,
          duplicate: false,
          invalid: false,
          invalid_volume: false,
          pattern_member: false,
          caption: "Settlement never arrived",
        },
      ],
      vwap: { name_breaks: true, pattern_hours: ["16:00-17:00 America/Chicago"] },
      picture: {
        kind: "gaps_ribbon",
        caption: "4 consecutive minute slots missing at the 17:00 CT open on 2025-06-12.",
        rule_ids: ["CMP.MISSING_TIMESTAMP"],
        slots: [
          { label: "17:00", present: false },
          { label: "17:01", present: false },
          { label: "17:02", present: true },
          { label: "17:03", present: true },
        ],
      },
    },
    meta: {},
    ...overrides,
  };
}

export const bars: BarsResponse = {
  scope: {
    contracts: ["ESZ25"],
    start: null,
    end: null,
    basis: "clean",
    frequency: "minute",
    frequency_defaulted: false,
  },
  data: [
    {
      contract_id: "ESZ25",
      trade_date: "2025-06-02",
      open: 6010,
      high: 6018,
      low: 6005,
      close: 6014,
      volume: 142000,
      record_count: 1380,
      expected_count: 1380,
      completeness_pct: 100,
      finding_count: 1,
      max_severity: "warning",
    },
    {
      contract_id: "ESZ25",
      trade_date: "2025-06-03",
      open: 6014,
      high: 6022,
      low: 6008,
      close: 6019,
      volume: 168000,
      record_count: 1380,
      expected_count: 1380,
      completeness_pct: 100,
      finding_count: 0,
      max_severity: null,
    },
  ],
  total: 2,
  meta: { bar_source: "derived_from_minute" },
};

export const vwap: VwapResponse = {
  scope: {
    contracts: ["ESZ25"],
    start: null,
    end: null,
    basis: "clean",
    frequency: "minute",
    frequency_defaulted: false,
  },
  window: "15m",
  window_type: "trailing_time_range_inclusive",
  price_basis: "typical",
  partition: ["contract_id", "trade_date"],
  // The first window is null: volume was dropped with the missing open slots. A break, not a
  // connected line.
  data: [
    { ts_utc: "2025-06-12T22:00:00Z", vwap: null },
    { ts_utc: "2025-06-12T22:15:00Z", vwap: 6044.2 },
    { ts_utc: "2025-06-12T22:30:00Z", vwap: 6045.1 },
  ],
  total: 3,
};

export const batches: BatchesResponse = {
  data: [
    {
      batch_id: "b1",
      status: "loaded",
      filename: "ESZ25.parquet",
      file_format: "parquet",
      origin: "demo",
      frequency: "minute",
      rows_accepted: 114477,
      contracts_detected: ["ESZ25"],
    },
    {
      batch_id: "b2",
      status: "loaded",
      filename: "daily.csv",
      file_format: "csv",
      origin: "demo",
      frequency: "daily",
      rows_accepted: 1145,
      contracts_detected: ["ESZ25", "SBH26"],
    },
  ],
  total: 2,
};

export const corpus: CorpusDescription = {
  repo: "lynx1231/historical-futures-data-sample",
  revision: "29efdfa21c5a5b2d7aa306397385cf116e011559",
  url: "https://huggingface.co/datasets/lynx1231/historical-futures-data-sample",
  approx_mb: 16,
  minute_files: 8,
  licence_note:
    "The publisher grants no licence: the dataset is public and ungated, so downloading it " +
    "for evaluation is plainly intended, but nothing authorises redistribution.",
};

export const injection: InjectionResponse = {
  loaded: true,
  filename: "SR3G26_with_defects.csv",
  manifest_available: true,
  source: "SR3G26.csv",
  output: "SR3G26_with_defects.csv",
  rows_in: 345,
  rows_out: 346,
  seed: 20260906,
  groups: [
    {
      family: "invalid",
      label: "Invalid values",
      defects: [
        {
          source_row: 12,
          rule_id: "VAL.NEGATIVE_VOLUME",
          kind: "negate_volume",
          original: "100",
          injected: "-100",
        },
      ],
    },
    {
      family: "off_strip",
      label: "Other (off the strip)",
      defects: [
        {
          source_row: 40,
          rule_id: "TIM.OUT_OF_ORDER",
          kind: "swap_rows",
          original: null,
          injected: null,
        },
      ],
    },
  ],
};

export interface StubOptions {
  health?: Partial<Health>;
  contracts?: Contract[];
  checks?: (params: URLSearchParams) => ChecksResponse;
  /** An RFC 7807 problem to answer `/analytics/vwap` with, instead of the line. */
  vwapProblem?: { status: number; code: string; title: string; detail: string };
  injection?: InjectionResponse;
  /** NDJSON lines a `/demo/*` POST should answer with. */
  demoEvents?: Record<string, unknown>[];
}

/** Requests the stub saw, in order. Assertable: which routes a page actually called. */
export interface StubCalls {
  paths: string[];
}

/**
 * Install a `fetch` that answers the v1 routes this app reads.
 *
 * Anything unrecognised is a 404 problem rather than a silent `undefined`, so a page that
 * invents a route fails on the route rather than three renders later on a missing key.
 */
export function stubApi(options: StubOptions = {}): StubCalls {
  const calls: StubCalls = { paths: [] };

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const url = new URL(raw, "http://localhost");
      const path = url.pathname;
      calls.paths.push(path + url.search);

      if (path === "/v1/health") return json({ ...health, ...options.health });
      if (path === "/v1/contracts") {
        const data = options.contracts ?? contracts;
        return json({ data, total: data.length });
      }
      if (path === "/v1/dq/checks") {
        const params = url.searchParams;
        const body = options.checks
          ? options.checks(params)
          : checksFor(params.get("family") ?? "gaps");
        return json(body);
      }
      if (path === "/v1/analytics/bars/daily") return json(bars);
      if (path === "/v1/analytics/vwap") {
        if (options.vwapProblem) {
          const problem = options.vwapProblem;
          return json(
            {
              type: "/errors/frequency-unavailable",
              title: problem.title,
              status: problem.status,
              detail: problem.detail,
              code: problem.code,
            },
            problem.status,
          );
        }
        return json(vwap);
      }
      if (path === "/v1/ingest/batches") return json(batches);
      if (path === "/v1/demo/corpus") return json(corpus);
      if (path === "/v1/demo/injection") return json(options.injection ?? injection);
      if (path.startsWith("/v1/demo/") && init?.method === "POST") {
        const lines = options.demoEvents ?? [
          { event: "started", message: "Fetching the sample corpus…", phase: "fetch" },
          { event: "done", message: "Loaded 48 files (46 Parquet, 2 CSV)", loaded: 48 },
        ];
        return new Response(lines.map((line) => JSON.stringify(line)).join("\n") + "\n", {
          status: 200,
          headers: { "Content-Type": "application/x-ndjson" },
        });
      }
      return json(
        { title: "Not Found", status: 404, detail: `no stub for ${path}` },
        404,
      );
    }),
  );

  return calls;
}
