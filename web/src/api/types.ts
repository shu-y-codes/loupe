/**
 * The envelopes this app reads, hand-written against `specs/api-contract.md`.
 *
 * **These are not the source of truth — the API is.** `npm run types` pulls
 * `/v1/openapi.json` into `src/api/schema.json` (which `src/api/schema.test.ts` reads, and
 * which fails the build if a test stub invents a key the API does not have) and into
 * `src/api/schema.ts` (`openapi-typescript`'s output, a lookup aid when you want to check a
 * shape). Both are gitignored; a committed copy can go stale without anything noticing.
 *
 * These interfaces are hand-written rather than generated because a
 * `components["schemas"]["…"]` lookup at every call site reads worse than a name, and because
 * the app deliberately reads a subset — `score` and `scope_signature` arrive on the checks
 * envelope and this UI does not draw them (`specs/loupe-ui-design.md`, Missing grain). What
 * keeps hand-written from meaning invented is the parity guard.
 */

export type Frequency = "minute" | "daily";
export type Family = "gaps" | "duplicates" | "invalid" | "patterns";

export const FAMILY_ORDER: readonly Family[] = [
  "gaps",
  "duplicates",
  "invalid",
  "patterns",
];

export const FAMILY_LABEL: Record<Family, string> = {
  gaps: "Gaps",
  duplicates: "Duplicates",
  invalid: "Invalid values",
  patterns: "Recurring patterns",
};

export interface Health {
  status: string;
  schema_applied: boolean;
  rules_seeded: boolean;
  records: number;
  contracts: number;
  batches: number;
  synthetic_batches: number;
  synthetic_records: number;
}

export interface Coverage {
  first_trade_date: string | null;
  last_trade_date: string | null;
  sessions: number;
  records: number;
}

export interface Contract {
  contract_id: string;
  root: string | null;
  exchange: string | null;
  contract_month: string | null;
  tick_size: number | null;
  multiplier: number | null;
  coverage: Record<string, Coverage>;
  frequencies_available: string[];
  roll_date: string | null;
  dates_inferred: boolean;
}

export interface FamilyCard {
  family: string;
  label: string;
  count: number;
  unit: string;
  detail: string;
}

export interface AggregatedIssue {
  family: string;
  what: string;
  days: number;
  records: number;
  what_we_did: string;
}

export interface OverlayMark {
  trade_date: string;
  /** `present`, `absent`, or `holiday`. */
  session: string;
  partial_gap: boolean;
  duplicate: boolean;
  invalid: boolean;
  invalid_volume: boolean;
  pattern_member: boolean;
  caption: string;
}

export interface PictureSlot {
  label: string;
  present: boolean;
}

export interface PatternBucket {
  label: string;
  share_of_findings: number;
  share_of_records: number;
  lift: number;
  support: number;
  distinct_days: number;
}

/**
 * `kind` is `gaps_ribbon`, `absent_session`, `duplicate_rows`, `invalid_cell`,
 * `pattern_histogram`, or `empty`. The rest of the payload depends on it.
 */
export interface Picture {
  kind?: string;
  caption?: string;
  rule_ids?: string[];
  slots?: PictureSlot[];
  rows?: Record<string, unknown>[];
  field?: string;
  evidence_frequency?: string;
  evidence_source?: string;
  bar?: Record<string, unknown>;
  buckets?: PatternBucket[];
  buckets_shown?: number;
  patterns_total?: number;
  axis_label?: string;
  dimension?: string;
}

export interface Overlay {
  family: string;
  ohlcv: OverlayMark[];
  /** `pattern_hours` and `name_breaks`, already filtered to the selected quality grain. */
  vwap: { name_breaks?: boolean; pattern_hours?: string[] };
  picture: Picture;
}

export interface Scope {
  contracts: string[];
  start: string | null;
  end: string | null;
  basis: string | null;
  frequency: string | null;
  frequency_defaulted: boolean;
}

export interface ChecksResponse {
  scope: Scope;
  contract_id: string;
  score: number | null;
  scope_signature: string | null;
  dimensions_not_in_scope: Record<string, unknown>[];
  frequencies: string[];
  /** True when a completed run exists. Zero on a card then means the check ran. */
  checked: boolean;
  families: FamilyCard[];
  issues: AggregatedIssue[];
  overlay: Overlay;
  meta: Record<string, unknown>;
}

export interface Bar {
  contract_id: string;
  trade_date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  record_count: number | null;
  expected_count: number | null;
  completeness_pct: number | null;
  finding_count: number;
  /** Stays on the envelope for the publish gate. This UI does not paint with it. */
  max_severity: string | null;
}

export interface BarsResponse {
  scope: Scope;
  data: Bar[];
  total: number;
  /** `bar_source` says whether the series was derived from minute or supplied daily. */
  meta: { bar_source?: string } & Record<string, unknown>;
}

export interface VwapPoint {
  ts_utc: string;
  vwap: number | null;
}

export interface VwapResponse {
  scope: Scope;
  window: string;
  window_type: string;
  price_basis: string;
  partition: string[];
  data: VwapPoint[];
  total: number;
}

export interface BatchSummary {
  batch_id: string;
  status: string;
  filename: string;
  file_format: string | null;
  origin: string;
  frequency: string;
  rows_accepted: number;
  contracts_detected: string[];
}

export interface BatchesResponse {
  data: BatchSummary[];
  total: number;
}

export interface CorpusDescription {
  repo: string;
  revision: string;
  url: string;
  approx_mb: number;
  minute_files: number;
  licence_note: string;
}

export interface PlantedDefect {
  source_row: number | null;
  rule_id: string;
  kind: string;
  original: string | null;
  injected: string | null;
}

export interface PlantedGroup {
  family: string;
  label: string;
  defects: PlantedDefect[];
}

export interface InjectionResponse {
  loaded: boolean;
  filename: string | null;
  manifest_available: boolean;
  source: string | null;
  output: string | null;
  rows_in: number | null;
  rows_out: number | null;
  seed: number | null;
  groups: PlantedGroup[];
}

/** One NDJSON line from a demo route. */
export interface DemoEvent {
  event: "started" | "progress" | "warning" | "error" | "done";
  message: string;
  phase?: string;
  done?: number;
  total?: number;
  file?: string;
  title?: string;
  hint?: string;
  loaded?: number;
  planted?: number;
  restored?: boolean;
}
