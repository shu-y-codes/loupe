/**
 * The app shell: ask `/health`, then draw one of two destinations.
 *
 * `/health` comes first and everything depends on the *body*, not on a yes/no. The demo panel
 * decides which controls to offer from `records`, and the synthetic disclosure fires on
 * `synthetic_batches` — and that disclosure has to be driven by something the page cannot
 * skip, which is why it reads the call that already gates everything else. There is no route
 * to either destination that does not pass through it.
 *
 * Failures are answered in place with the sentence they earned, and none of them invites an
 * uploader: there isn't one (`specs/loupe-ui-design.md`, Empty, daily-only, and no-finding
 * states).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiProblem, ApiUnavailable, api } from "./api/client";
import type {
  Bar,
  ChecksResponse,
  Contract,
  Family,
  Frequency,
  Health,
  VwapPoint,
} from "./api/types";
import { DemoPanel } from "./components/DemoPanel";
import { Sidebar } from "./components/Sidebar";
import { Callout, Caption, Stack } from "./components/primitives";
import { SyntheticNotice } from "./components/SyntheticNotice";
import { Overview, type OverviewRow } from "./pages/Overview";
import { Review } from "./pages/Review";
import { heldGrains, resolveFrequency, reviewHeaderParts, useAppState } from "./state";

/** Overview's rows, and the store fingerprint they describe. */
interface OverviewCache {
  fingerprint: string;
  rows: OverviewRow[];
}

export function App() {
  const state = useAppState();
  const overviewCache = useState<OverviewCache | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const refresh = useCallback(() => setReload((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    setFailure(null);
    Promise.all([api.health(), api.contracts().catch(() => [] as Contract[])])
      .then(([body, rows]) => {
        if (!live) return;
        setHealth(body);
        setContracts(rows);
      })
      .catch((error: unknown) => {
        if (!live) return;
        setHealth(null);
        setFailure(describe(error));
      });
    return () => {
      live = false;
    };
  }, [reload]);

  // A contract that is no longer loaded must not stay selected; the first one is the default.
  const { contract, setContract, frequency, setFrequency } = state;
  useEffect(() => {
    if (contracts.length === 0) return;
    if (!contract || !contracts.some((row) => row.contract_id === contract)) {
      setContract(contracts[0]?.contract_id ?? null);
    }
  }, [contracts, contract, setContract]);

  const selected = contracts.find((row) => row.contract_id === contract);
  const available = heldGrains(selected);
  const resolved = resolveFrequency(available, frequency);
  useEffect(() => {
    if (resolved && resolved !== frequency) setFrequency(resolved);
  }, [resolved, frequency, setFrequency]);

  return (
    <div style={{ display: "flex", minHeight: "100%", alignItems: "stretch" }}>
      <Sidebar state={state} contracts={contracts}>
        {health ? (
          <DemoPanel health={health} contracts={contracts} onChanged={refresh} />
        ) : null}
      </Sidebar>

      <main
        style={{
          flex: 1,
          minWidth: 0,
          padding: "20px 24px 48px",
          maxWidth: 1120,
        }}
      >
        <Stack gap={16}>
          {failure ? <Callout tone="danger" title="The API did not answer">{failure}</Callout> : null}
          {health ? (
            <Ready
              health={health}
              contracts={contracts}
              state={state}
              frequency={resolved}
              reload={reload}
              overviewCache={overviewCache}
            />
          ) : failure ? null : (
            <Caption>Loading…</Caption>
          )}
        </Stack>
      </main>
    </div>
  );
}

/**
 * Whether the store can answer at all, with a sentence when it cannot.
 *
 * A store with no schema answers every analytic call with a refusal — `dq.dq_run` does not
 * exist to be queried. Blaming the reader for a setup step nobody told them about would be the
 * wrong response, so the page checks first and says what to run.
 */
function Ready({
  health,
  contracts,
  state,
  frequency,
  reload,
  overviewCache,
}: {
  health: Health;
  contracts: Contract[];
  state: ReturnType<typeof useAppState>;
  frequency: Frequency | null;
  reload: number;
  overviewCache: [OverviewCache | null, (next: OverviewCache | null) => void];
}) {
  if (!health.schema_applied) {
    return (
      <Callout tone="warning" title="The store has no schema yet">
        <Stack gap={6}>
          <span>
            Start the API with the bootstrapping factory, which applies the schema and seeds the
            rule catalogue on first run:
          </span>
          <code>uv run uvicorn loupe.api.app:bootstrapped_app --factory</code>
        </Stack>
      </Callout>
    );
  }
  if (!health.rules_seeded) {
    return (
      <Callout tone="warning" title="The rule catalogue is not seeded">
        Restart the API with <code>loupe.api.app:bootstrapped_app</code>, or run{" "}
        <code>seed_quality(con)</code> — quality rules are rows, so nothing can be validated
        until they exist.
      </Callout>
    );
  }

  return (
    <Stack gap={16}>
      <Heading state={state} contracts={contracts} frequency={frequency} />
      {/* Before anything that reports a number. A reader must never meet a count without
          knowing whether the data behind it was planted. */}
      <SyntheticNotice health={health} />
      {state.destination === "Overview" ? (
        <OverviewPage
          health={health}
          contracts={contracts}
          state={state}
          cache={overviewCache}
        />
      ) : (
        <ReviewPage contracts={contracts} state={state} frequency={frequency} reload={reload} />
      )}
    </Stack>
  );
}

function Heading({
  state,
  contracts,
  frequency,
}: {
  state: ReturnType<typeof useAppState>;
  contracts: Contract[];
  frequency: Frequency | null;
}) {
  if (state.destination === "Overview") {
    return (
      <Stack gap={2}>
        <h1>Loupe</h1>
        <Caption>Overview · loaded contracts by grain · full held window</Caption>
        <Caption>Select a row to open it in Review</Caption>
      </Stack>
    );
  }
  const metadata = contracts.find((row) => row.contract_id === state.contract);
  return (
    <Stack gap={2}>
      <h1>Loupe</h1>
      <Caption>
        {state.contract
          ? reviewHeaderParts(
              state.contract,
              metadata,
              frequency,
              state.start,
              state.end,
            ).join(" · ")
          : "Four checks and two charts on one selected contract."}
      </Caption>
    </Stack>
  );
}

// ------------------------------------------------------------------------------ Overview

/**
 * Bust the Overview cache when the store's *contents* change, not on every visit.
 *
 * Overview costs one `GET /dq/checks` per contract × grain — 48 requests on the sample corpus.
 * Paying that again because someone looked at Review and came back is the loop
 * `specs/loupe-ui-design.md` says to cache, so the rows are held in `App` (which never
 * unmounts) rather than in the page, and refetched only when this string changes.
 */
function storeFingerprint(health: Health, contracts: Contract[]): string {
  return [
    health.records,
    health.batches,
    health.synthetic_batches,
    contracts.map((row) => row.contract_id).sort().join(","),
  ].join("|");
}

function OverviewPage({
  health,
  contracts,
  state,
  cache,
}: {
  health: Health;
  contracts: Contract[];
  state: ReturnType<typeof useAppState>;
  /** Lives in `App`, so switching destinations does not re-hit 48 endpoints. */
  cache: [OverviewCache | null, (next: OverviewCache | null) => void];
}) {
  const [cached, setCached] = cache;
  const fingerprint = storeFingerprint(health, contracts);
  const rows = cached && cached.fingerprint === fingerprint ? cached.rows : null;

  // One (contract, frequency) per held grain. Minute before daily when both exist.
  const scopes = useMemo(
    () =>
      contracts.flatMap((contract) =>
        heldGrains(contract).map((frequency) => ({ contract, frequency })),
      ),
    [contracts],
  );

  useEffect(() => {
    if (rows !== null) return;
    let live = true;
    if (scopes.length === 0) {
      setCached({ fingerprint, rows: [] });
      return;
    }
    Promise.all(
      scopes.map(async ({ contract, frequency }): Promise<OverviewRow> => {
        const base = {
          contract_id: contract.contract_id,
          root: contract.root,
          exchange: contract.exchange,
          dual: heldGrains(contract).length > 1,
          frequency,
        };
        try {
          // Full held window — no start/end, matching the empty date pickers.
          const body = await api.checks({
            contract: contract.contract_id,
            family: "gaps",
            frequency,
          });
          return {
            ...base,
            checked: body.checked,
            families: Object.fromEntries(
              (body.families ?? []).map((card) => [card.family, card]),
            ),
          };
        } catch (error) {
          return { ...base, checked: null, families: {}, error: describe(error) };
        }
      }),
    ).then((result) => {
      if (live) setCached({ fingerprint, rows: result });
    });
    return () => {
      live = false;
    };
    // `setCached` and `fingerprint` are stable for a given store; re-running on `rows` is what
    // makes a fingerprint change (a demo action) refetch and nothing else does.
  }, [scopes, rows, fingerprint, setCached]);

  if (rows === null) return <Caption>Reading the corpus…</Caption>;
  return <Overview rows={rows} onOpen={state.openInReview} />;
}

// -------------------------------------------------------------------------------- Review

interface ReviewData {
  /** The scope this envelope answers. Rendered only while it still matches the selection. */
  scope: string;
  checks: ChecksResponse;
  bars: { data: Bar[]; meta: { bar_source?: string } };
  vwap: { data: VwapPoint[] } | ApiProblem | null;
}

function ReviewPage({
  contracts,
  state,
  frequency,
  reload,
}: {
  contracts: Contract[];
  state: ReturnType<typeof useAppState>;
  frequency: Frequency | null;
  reload: number;
}) {
  const [data, setData] = useState<ReviewData | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const { contract, family, start, end } = state;
  // Contract, grain and dates change *what the page is about*; family changes only which
  // marks are drawn on it. So a scope change discards what is on screen and a family change
  // does not — blanking the charts on every card click would be worse than a moment's lag,
  // and it would drop the zoom the spec says a family change preserves.
  const scopeKey = `${contract}|${frequency}|${start}|${end}`;

  useEffect(() => {
    if (!contract || !frequency) return;
    let live = true;
    setFailure(null);
    (async () => {
      const checks = await api.checks({ contract, family, frequency, start, end });
      const bars = await api
        .barsDaily({ contract, frequency, start, end })
        // A refused or empty bar envelope is a chart with nothing to draw, not a dead page.
        .catch(() => ({ data: [] as Bar[], meta: {} }));
      // The VWAP refusal is content, so it is caught and carried rather than swallowed.
      const vwap = await api
        .vwap({ contract, start, end })
        .catch((error: unknown) =>
          error instanceof ApiProblem
            ? error
            : new ApiProblem({ status: 503, title: "Unavailable", detail: describe(error) }),
        );
      if (live) setData({ scope: scopeKey, checks, bars, vwap });
    })().catch((error: unknown) => {
      if (!live) return;
      setData(null);
      setFailure(describe(error));
    });
    return () => {
      live = false;
    };
  }, [contract, frequency, family, start, end, reload, scopeKey]);

  if (contracts.length === 0 || !contract) {
    return (
      <Callout tone="info">
        No contracts loaded yet. Load demo data from the sidebar to see quality for it.
      </Callout>
    );
  }
  if (!frequency) {
    return (
      <Callout tone="warning">
        The selected contract does not report a held quality grain.
      </Callout>
    );
  }
  if (failure) return <Callout tone="danger">{failure}</Callout>;
  // Stale scope: the header already names the new contract, so leaving the old contract's
  // cards and candles under it would put a number on screen that is about something else.
  if (!data || data.scope !== scopeKey) return <Caption>Reading checks…</Caption>;

  return (
    <Review
      checks={data.checks}
      bars={data.bars}
      vwap={data.vwap}
      family={family as Family}
      onSelectFamily={state.setFamily}
      scope={{ contract, frequency, start, end }}
    />
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiUnavailable) return error.message;
  if (error instanceof ApiProblem) return `${error.title}: ${error.detail ?? ""}`.trim();
  return error instanceof Error ? error.message : String(error);
}
