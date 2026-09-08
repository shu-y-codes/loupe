/**
 * Stub parity: every key the test stub invents must be a key the API actually has.
 *
 * This is the guard `tests/ui/` had and the one thing a stubbed-`fetch` tier cannot do
 * without. A stub is a place to invent a field, and a page that reads the invented field
 * passes its own test forever while the real envelope has never carried it.
 *
 * The document is read from `src/api/schema.json`, which `npm run types` pulls from a
 * running API's `/v1/openapi.json`. **When it is absent these tests skip**, so a checkout with
 * no server can still run the suite — and CI, which starts the API to generate it, cannot.
 * A skipped guard is visible in the report; a guard that silently passed would not be.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as stub from "../test/stub";

interface OpenApi {
  paths: Record<string, Record<string, unknown>>;
  components: { schemas: Record<string, { properties?: Record<string, unknown> }> };
}

function loadSchema(): OpenApi | null {
  // Read rather than imported: the file is gitignored and often absent, and a static import
  // of a missing module is a compile error rather than the skip this test wants.
  const path = resolve(dirname(fileURLToPath(import.meta.url)), "schema.json");
  try {
    return JSON.parse(readFileSync(path, "utf8")) as OpenApi;
  } catch {
    return null;
  }
}

const schema = loadSchema();
const guard = schema ? describe : describe.skip;

function propertiesOf(document: OpenApi, name: string): Set<string> {
  return new Set(Object.keys(document.components.schemas[name]?.properties ?? {}));
}

function assertKeys(document: OpenApi, name: string, sample: Record<string, unknown>): void {
  const known = propertiesOf(document, name);
  expect(known.size, `${name} has no properties in the document`).toBeGreaterThan(0);
  for (const key of Object.keys(sample)) {
    expect(known, `${name} has no field \`${key}\` — the stub invented it`).toContain(key);
  }
}

guard("the stub matches the generated OpenAPI document", () => {
  const document = schema as OpenApi;

  it("serves every route the client calls", () => {
    for (const path of [
      "/v1/health",
      "/v1/contracts",
      "/v1/dq/checks",
      "/v1/analytics/bars/daily",
      "/v1/analytics/vwap",
      "/v1/ingest/batches",
      "/v1/demo/corpus",
      "/v1/demo/load",
      "/v1/demo/inject",
      "/v1/demo/remove",
      "/v1/demo/injection",
    ]) {
      expect(Object.keys(document.paths), `the API has no ${path}`).toContain(path);
    }
  });

  it("invents no key on health, contracts or coverage", () => {
    assertKeys(document, "Health", stub.health as unknown as Record<string, unknown>);
    assertKeys(document, "Contract", stub.contracts[0] as unknown as Record<string, unknown>);
    assertKeys(
      document,
      "Coverage",
      stub.contracts[0]!.coverage.minute as unknown as Record<string, unknown>,
    );
  });

  it("invents no key on the checks envelope", () => {
    const checks = stub.checksFor();
    assertKeys(document, "DqChecksResponse", checks as unknown as Record<string, unknown>);
    assertKeys(document, "FamilyCard", checks.families[0] as unknown as Record<string, unknown>);
    assertKeys(document, "AggregatedIssue", checks.issues[0] as unknown as Record<string, unknown>);
    assertKeys(document, "Overlay", checks.overlay as unknown as Record<string, unknown>);
    assertKeys(
      document,
      "OverlayMark",
      checks.overlay.ohlcv[0] as unknown as Record<string, unknown>,
    );
    assertKeys(document, "Scope", checks.scope as unknown as Record<string, unknown>);
  });

  it("invents no key on the analytics envelopes", () => {
    assertKeys(document, "BarsResponse", stub.bars as unknown as Record<string, unknown>);
    assertKeys(document, "VwapResponse", stub.vwap as unknown as Record<string, unknown>);
    assertKeys(document, "VwapPoint", stub.vwap.data[0] as unknown as Record<string, unknown>);
  });

  it("invents no key on bars, batches or the demo envelopes", () => {
    assertKeys(document, "Bar", stub.bars.data[0] as unknown as Record<string, unknown>);
    assertKeys(document, "BatchesResponse", stub.batches as unknown as Record<string, unknown>);
    assertKeys(
      document,
      "BatchSummary",
      stub.batches.data[0] as unknown as Record<string, unknown>,
    );
    assertKeys(document, "CorpusDescription", stub.corpus as unknown as Record<string, unknown>);
    assertKeys(document, "InjectionResponse", stub.injection as unknown as Record<string, unknown>);
    assertKeys(
      document,
      "PlantedGroup",
      stub.injection.groups[0] as unknown as Record<string, unknown>,
    );
    assertKeys(
      document,
      "PlantedDefect",
      stub.injection.groups[0]!.defects[0] as unknown as Record<string, unknown>,
    );
  });
});
