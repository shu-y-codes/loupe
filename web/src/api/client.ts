/**
 * The only thing in the app that knows the API exists.
 *
 * One module holds the base path, the verbs and the error translation. It is the layer
 * boundary `specs/loupe-solution-design.md` §6 draws — the UI owns pages and a thin client,
 * never SQL, rule logic or aggregation — and it is the seam the page tests stub, which is what
 * lets them assert view assembly without a server or a database.
 *
 * **Relative paths, deliberately.** `/v1/...` and never an absolute origin: Vite proxies `/v1`
 * to uvicorn in development, and FastAPI serves the built app beside `/v1` in production. Same
 * origin either way, so there is no CORS policy to write and no base URL to configure wrong.
 */

import type {
  BarsResponse,
  BatchesResponse,
  ChecksResponse,
  Contract,
  CorpusDescription,
  DemoEvent,
  Health,
  InjectionResponse,
  VwapResponse,
} from "./types";

export const BASE = "/v1";

/** The API did not answer at all. Distinct from an error it *did* answer with. */
export class ApiUnavailable extends Error {
  constructor(message?: string) {
    super(
      message ??
        "No answer from the API. Is it running? " +
          "`uv run uvicorn loupe.api.app:create_app --factory`",
    );
    this.name = "ApiUnavailable";
  }
}

/**
 * An RFC 7807 problem the API returned, carried whole.
 *
 * A refusal is information, not a failure to render: `CAP.FREQUENCY_UNAVAILABLE` on a
 * daily-only contract is the VWAP panel's content, not an empty chart. Pages catch this and
 * explain in place, so `code` and `detail` survive the trip.
 */
export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly title: string;
  readonly detail: string | null;
  readonly meta: Record<string, unknown> | null;

  constructor(init: {
    status: number;
    code?: string | null;
    title: string;
    detail?: string | null;
    meta?: Record<string, unknown> | null;
  }) {
    super(init.detail ?? init.title);
    this.name = "ApiProblem";
    this.status = init.status;
    this.code = init.code ?? null;
    this.title = init.title;
    this.detail = init.detail ?? null;
    this.meta = init.meta ?? null;
  }
}

export type QueryValue = string | number | boolean | null | undefined;

/** Drop unset filters, and spell values the way the contract does. */
export function queryString(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

async function problemFrom(response: Response): Promise<ApiProblem> {
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === "object") body = parsed as Record<string, unknown>;
  } catch {
    // A 4xx body is *usually* RFC 7807, but not always, and a body that will not parse is
    // still a refusal with a status line worth reporting.
  }
  return new ApiProblem({
    status: response.status,
    code: (body.code as string | undefined) ?? null,
    title: (body.title as string | undefined) ?? response.statusText ?? "Request failed",
    detail: (body.detail as string | undefined) ?? null,
    meta: (body.meta as Record<string, unknown> | undefined) ?? null,
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (cause) {
    throw new ApiUnavailable(
      `No answer from ${BASE}. Is the API running? ` +
        "`uv run uvicorn loupe.api.app:create_app --factory`" +
        (cause instanceof Error ? ` (${cause.message})` : ""),
    );
  }
  if (!response.ok) throw await problemFrom(response);
  return (await response.json()) as T;
}

export interface ChecksParams {
  contract: string;
  family: string;
  frequency?: string | null;
  start?: string | null;
  end?: string | null;
  basis?: string;
}

export const api = {
  health: () => request<Health>("/health"),

  contracts: () =>
    request<{ data: Contract[]; total: number }>("/contracts").then((body) => body.data),

  /** `GET /v1/dq/checks` — cards, overlay marks, picture and aggregated issues. */
  checks: (params: ChecksParams) =>
    request<ChecksResponse>(`/dq/checks${queryString({ ...params })}`),

  barsDaily: (params: {
    contract: string;
    frequency?: string | null;
    start?: string | null;
    end?: string | null;
  }) =>
    request<BarsResponse>(
      `/analytics/bars/daily${queryString({ ...params, basis: "clean" })}`,
    ),

  vwap: (params: { contract: string; start?: string | null; end?: string | null }) =>
    request<VwapResponse>(`/analytics/vwap${queryString({ ...params })}`),

  batches: () => request<BatchesResponse>("/ingest/batches"),

  demoCorpus: () => request<CorpusDescription>("/demo/corpus"),

  injection: () => request<InjectionResponse>("/demo/injection"),
};

/**
 * Read one demo route's NDJSON stream, calling `onEvent` per line as it arrives.
 *
 * Streamed rather than awaited because a minute of silence after a button press reads as a
 * hang. The lines are UI telemetry: there is no handle and nothing to poll, and the `done`
 * event *is* the result (`specs/api-contract.md` §4.4).
 */
export async function streamDemo(
  path: "/demo/load" | "/demo/inject" | "/demo/remove",
  onEvent: (event: DemoEvent) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { method: "POST" });
  } catch (cause) {
    throw new ApiUnavailable(cause instanceof Error ? cause.message : undefined);
  }
  if (!response.ok) throw await problemFrom(response);
  if (!response.body) {
    // No streaming body (a test stub, or a proxy that buffered): the text is still NDJSON.
    for (const line of (await response.text()).split("\n")) emit(line, onEvent);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Everything up to the last newline is complete lines; the tail may be half an object.
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) emit(line, onEvent);
  }
  emit(buffer, onEvent);
}

function emit(line: string, onEvent: (event: DemoEvent) => void): void {
  const text = line.trim();
  if (!text) return;
  try {
    onEvent(JSON.parse(text) as DemoEvent);
  } catch {
    // A truncated final line is not worth failing a load over.
  }
}
