/**
 * Pull `/v1/openapi.json` off a running API into `src/api/`.
 *
 * Two artefacts from one document, because they answer different questions. `schema.json` is
 * the raw document, read at runtime by `src/api/schema.test.ts` to check that no test stub has
 * invented a field. `schema.ts` is `openapi-typescript`'s output, which the compiler reads.
 *
 * Both are gitignored: the API is the source of truth, and a checked-in copy is a copy that
 * can be stale without anything noticing.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const origin = process.env.LOUPE_API_ORIGIN ?? "http://127.0.0.1:8000";
const url = `${origin}/v1/openapi.json`;
const out = resolve(dirname(fileURLToPath(import.meta.url)), "../src/api/schema.json");

let response;
try {
  response = await fetch(url);
} catch (cause) {
  console.error(
    `Could not reach ${url}. Start the API first:\n` +
      "  uv run uvicorn loupe.api.app:create_app --factory\n" +
      `(${cause instanceof Error ? cause.message : String(cause)})`,
  );
  process.exit(1);
}
if (!response.ok) {
  console.error(`${url} answered ${response.status}.`);
  process.exit(1);
}

await mkdir(dirname(out), { recursive: true });
await writeFile(out, JSON.stringify(await response.json(), null, 2) + "\n");
console.log(`wrote ${out}`);
