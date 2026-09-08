/**
 * The demo panel: load real vendor data, then — separately — plant labelled defects.
 *
 * Two buttons, and the separation between them is the whole design. A reviewer has to be able
 * to see real findings on real vendor data *and know that is what they are looking at* before
 * anything synthetic exists in the store. Bundling the injection into "Load demo data" would
 * make every number on the screen ambiguous.
 *
 * **Consent before bytes.** `specs/sample-corpus.md` §1 found no licence grant anywhere in the
 * vendor package — public and ungated, so downloading for evaluation is plainly intended, but
 * nothing authorises redistribution. So the panel says what it is about to download and from
 * where, and waits for a press. `GET /v1/demo/corpus` supplies that sentence and makes no
 * network call of its own.
 *
 * **The work happens on the server now.** A browser cannot reach Hugging Face on the app's
 * behalf, read `data/samples/`, or write a defective copy, so the buttons POST to
 * `/v1/demo/load|inject|remove` and render the NDJSON progress those routes stream. What is
 * shown is the same "Fetching 3/48 · filename" line the Streamlit panel drew, one layer out.
 */

import { useEffect, useState } from "react";
import { api, streamDemo } from "../api/client";
import type { BatchSummary, Contract, CorpusDescription, DemoEvent, Health } from "../api/types";
import { theme } from "../theme/theme";
import { Callout, Caption, Stack, Text } from "./primitives";

/** Demo CSV rows: a format fact, not a defect (`specs/loupe-ui-design.md`). */
export const CONVERTED_MARK = "Converted from Parquet";

export const COVERAGE_BOTH = "Daily + minute";
export const COVERAGE_DAILY = "Daily-only";
export const COVERAGE_MINUTE = "Minute-only";
const COVERAGE_ORDER = [COVERAGE_BOTH, COVERAGE_DAILY, COVERAGE_MINUTE] as const;

/**
 * CSV that arrived via demo load — converted from Parquet. Not any CSV.
 *
 * Keys off `file_format` / suffix **plus** `origin = demo`. After injection the planted file
 * is also a CSV; that mark is the synthetic disclosure, not this one.
 */
export function isDemoCsvConversion(batch: BatchSummary): boolean {
  const format = (batch.file_format ?? "").toLowerCase();
  const name = (batch.filename ?? "").toLowerCase();
  return batch.origin === "demo" && (format === "csv" || name.endsWith(".csv"));
}

function coverageLabel(grains: Set<string>): string | null {
  const held = [...grains].filter((grain) => grain === "daily" || grain === "minute");
  if (held.includes("daily") && held.includes("minute")) return COVERAGE_BOTH;
  if (held.length === 1 && held[0] === "daily") return COVERAGE_DAILY;
  if (held.length === 1 && held[0] === "minute") return COVERAGE_MINUTE;
  return null;
}

/**
 * Group ingested files by **contract** coverage, not by the file's own frequency.
 *
 * A contract that holds both grains lists both of its files under Daily + minute — the daily
 * file of a dual-grain contract does not sit in Daily-only.
 */
export function groupBatchesByCoverage(
  batches: BatchSummary[],
  contracts: Contract[],
): [string, BatchSummary[]][] {
  const grains = new Map<string, Set<string>>();
  for (const contract of contracts) {
    grains.set(contract.contract_id, new Set(contract.frequencies_available ?? []));
  }
  // Fall back to the batch's own frequency for a contract `/v1/contracts` has nothing for.
  for (const batch of batches) {
    for (const id of batch.contracts_detected ?? []) {
      const held = grains.get(id);
      if (!held || held.size === 0) {
        const next = held ?? new Set<string>();
        if (batch.frequency) next.add(batch.frequency);
        grains.set(id, next);
      }
    }
  }

  const buckets = new Map<string, BatchSummary[]>(COVERAGE_ORDER.map((key) => [key, []]));
  const seen = new Set<string>();
  for (const batch of batches) {
    const keys = new Set<string>();
    for (const id of batch.contracts_detected ?? []) {
      const label = coverageLabel(grains.get(id) ?? new Set());
      if (label) keys.add(label);
    }
    const bucket = keys.has(COVERAGE_BOTH)
      ? COVERAGE_BOTH
      : ([...keys][0] ?? coverageLabel(new Set([batch.frequency])));
    if (!bucket) continue;
    const id = batch.batch_id || batch.filename;
    if (seen.has(id)) continue;
    seen.add(id);
    buckets.get(bucket)?.push(batch);
  }
  return COVERAGE_ORDER.map((label) => [label, buckets.get(label) ?? []] as [string, BatchSummary[]])
    .filter(([, rows]) => rows.length > 0);
}

type Phase = { running: boolean; lines: DemoEvent[] };

const IDLE: Phase = { running: false, lines: [] };

export interface DemoPanelProps {
  health: Health;
  contracts: Contract[];
  /** Re-read `/health`, `/contracts` and the batch list after a demo action finishes. */
  onChanged: () => void;
}

export function DemoPanel({ health, contracts, onChanged }: DemoPanelProps) {
  const [phase, setPhase] = useState<Phase>(IDLE);
  const [batches, setBatches] = useState<BatchSummary[]>([]);

  const records = health.records ?? 0;
  const synthetic = health.synthetic_batches ?? 0;

  useEffect(() => {
    if (records === 0) return;
    let live = true;
    api
      .batches()
      .then((body) => {
        if (live) setBatches(body.data ?? []);
      })
      .catch(() => {
        if (live) setBatches([]);
      });
    return () => {
      live = false;
    };
  }, [records, synthetic]);

  const run = async (path: "/demo/load" | "/demo/inject" | "/demo/remove") => {
    setPhase({ running: true, lines: [] });
    try {
      await streamDemo(path, (event) =>
        setPhase((current) => ({ ...current, lines: [...current.lines, event] })),
      );
    } catch (error) {
      setPhase((current) => ({
        ...current,
        lines: [
          ...current.lines,
          { event: "error", message: String(error), title: "The request failed" },
        ],
      }));
    }
    setPhase((current) => ({ ...current, running: false }));
    onChanged();
  };

  return (
    <Stack gap={10}>
      <h3>Demo data</h3>
      {records === 0 ? (
        <LoadDemo running={phase.running} onLoad={() => void run("/demo/load")} />
      ) : (
        <>
          <Caption>{`${records.toLocaleString("en-US")} records loaded.`}</Caption>
          <IngestedFiles batches={batches} contracts={contracts} />
          {synthetic ? (
            <RemoveDefects
              health={health}
              running={phase.running}
              onRemove={() => void run("/demo/remove")}
            />
          ) : (
            <InjectDefects running={phase.running} onInject={() => void run("/demo/inject")} />
          )}
        </>
      )}
      <Progress phase={phase} />
    </Stack>
  );
}

function LoadDemo({ running, onLoad }: { running: boolean; onLoad: () => void }) {
  const [described, setDescribed] = useState<CorpusDescription | null>(null);

  useEffect(() => {
    let live = true;
    api
      .demoCorpus()
      .then((body) => {
        if (live) setDescribed(body);
      })
      .catch(() => {
        if (live) setDescribed(null);
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <Stack gap={8}>
      <Caption>
        {described
          ? `No data yet. Load ~${described.approx_mb} MB of real futures data from the ` +
            "publisher's Hugging Face dataset. Takes about a minute."
          : "No data yet. Load real futures data from the publisher's Hugging Face dataset."}
      </Caption>
      {/* Said before the button, not after it: the reader decides whether to download, and
          they cannot decide without knowing what and from where. */}
      {described ? (
        <details>
          <summary style={{ cursor: "pointer", fontSize: "var(--size-small)" }}>
            What this downloads
          </summary>
          <Stack gap={4} style={{ paddingTop: 6 }}>
            <Text size="small">
              <strong>{described.repo}</strong> at revision{" "}
              <code>{described.revision.slice(0, 12)}</code>
            </Text>
            <Text size="small">
              {`${described.minute_files} minute files and every daily file, checksum-verified ` +
                "against the vendor's own manifest."}
            </Text>
            <Caption>{described.licence_note}</Caption>
          </Stack>
        </details>
      ) : null}
      <Button primary disabled={running} onClick={onLoad}>
        Load demo data
      </Button>
    </Stack>
  );
}

function InjectDefects({ running, onInject }: { running: boolean; onInject: () => void }) {
  return (
    <Stack gap={8}>
      <Caption>
        Every finding above is real. The sample tape is close to defect-free, so several rules
        have no natural example in it.
      </Caption>
      <details>
        <summary style={{ cursor: "pointer", fontSize: "var(--size-small)" }}>
          Add labelled defects
        </summary>
        <Stack gap={4} style={{ paddingTop: 6 }}>
          <Text size="small">
            Writes a <strong>copy</strong> of one minute file with nine planted defects —
            negative volume, an inverted bar, a key conflict, a deleted run of slots and five
            more — and loads it in place of the clean one.
          </Text>
          <Text size="small">
            Every defect is labelled in a manifest naming the rule it should trip, and the app
            marks the data as synthetic for as long as it is loaded.
          </Text>
          <Caption>The vendor files on disk are never modified.</Caption>
        </Stack>
      </details>
      <Button disabled={running} onClick={onInject}>
        Inject demo defects
      </Button>
    </Stack>
  );
}

function RemoveDefects({
  health,
  running,
  onRemove,
}: {
  health: Health;
  running: boolean;
  onRemove: () => void;
}) {
  const [groups, setGroups] = useState<{ label: string }[]>([]);
  const [filename, setFilename] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .injection()
      .then((body) => {
        if (!live) return;
        setGroups(body.groups.map((group) => ({ label: group.label })));
        setFilename(body.filename);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [health.synthetic_batches]);

  return (
    <Stack gap={8}>
      {/* A warning Callout, not an emoji. Do not say "findings below were planted" —
          nothing follows that sentence in the sidebar. */}
      <Callout tone="warning">
        <strong>{`${(health.synthetic_records ?? 0).toLocaleString("en-US")} synthetic records`}</strong>{" "}
        are loaded.
      </Callout>
      {groups.length ? (
        <Stack gap={4}>
          <Caption>Planted in:</Caption>
          {groups.map((group) => (
            <div key={group.label}>
              <Text size="small" weight="semibold">
                {group.label}
              </Text>
              {filename ? <Caption>{filename}</Caption> : null}
            </div>
          ))}
        </Stack>
      ) : null}
      <Button disabled={running} onClick={onRemove}>
        Remove demo defects
      </Button>
    </Stack>
  );
}

function IngestedFiles({
  batches,
  contracts,
}: {
  batches: BatchSummary[];
  contracts: Contract[];
}) {
  if (batches.length === 0) return null;
  const groups = groupBatchesByCoverage(batches, contracts);
  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: "var(--size-small)" }}>
        {`${batches.length} ingested files`}
      </summary>
      <Stack gap={6} style={{ paddingTop: 6 }}>
        <Caption>What this store holds — not a directory of downloads.</Caption>
        {groups.map(([label, rows]) => (
          <Stack key={label} gap={2}>
            <Text size="small" weight="semibold">
              {label}
            </Text>
            {rows.map((batch) => (
              <Text key={batch.batch_id || batch.filename} size="small" tone="secondary">
                <code>{batch.filename}</code> · {batch.file_format ?? "—"} · {batch.origin}
                {isDemoCsvConversion(batch) ? ` · ${CONVERTED_MARK}` : ""}
              </Text>
            ))}
          </Stack>
        ))}
      </Stack>
    </details>
  );
}

/** The stream, rendered. The last line leads; errors keep their title and their hint. */
function Progress({ phase }: { phase: Phase }) {
  if (phase.lines.length === 0) return null;
  const last = phase.lines[phase.lines.length - 1];
  const warnings = phase.lines.filter((line) => line.event === "warning");
  const failure = phase.lines.find((line) => line.event === "error");

  return (
    <Stack gap={6} role="status" aria-live="polite">
      {failure ? (
        <Callout tone="danger" title={failure.title ?? "Failed"}>
          <Stack gap={4}>
            <Text size="small">{failure.message}</Text>
            {failure.hint ? <Caption>{failure.hint}</Caption> : null}
          </Stack>
        </Callout>
      ) : (
        <Caption>{last?.message ?? ""}</Caption>
      )}
      {warnings.map((warning, index) => (
        <Callout key={`${warning.message}-${index}`} tone="warning">
          <Text size="small">{warning.message}</Text>
        </Callout>
      ))}
    </Stack>
  );
}

function Button({
  primary = false,
  disabled,
  onClick,
  children,
}: {
  primary?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        border: `1px solid ${primary ? theme.stroke.focused : theme.stroke.primary}`,
        background: primary ? theme.text.primary : theme.bg.editor,
        color: primary ? theme.bg.editor : theme.text.primary,
        borderRadius: "var(--radius)",
        padding: "6px 10px",
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.6 : 1,
        width: "100%",
      }}
    >
      {children}
    </button>
  );
}
