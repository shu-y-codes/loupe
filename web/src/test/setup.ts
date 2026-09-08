/**
 * Test setup: jest-dom matchers, and a `fetch` that is stubbed by default.
 *
 * `fetch` is replaced rather than left alone so a component that reaches the network without
 * a stub fails loudly instead of hanging on a real request. Every page test installs its own
 * responses through `stubApi` (`src/test/stub.ts`).
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // `restoreAllMocks` does not undo `stubGlobal`, and a `fetch` left in place would answer
  // the next file's requests from the previous file's stub.
  vi.unstubAllGlobals();
});

// jsdom has no layout, so every measured box is 0×0 and the charts would divide by zero.
// A fixed box is closer to the truth than none.
Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
  writable: true,
  value: () => ({
    x: 0, y: 0, width: 720, height: 300, top: 0, left: 0, right: 720, bottom: 300,
    toJSON: () => ({}),
  }),
});

if (!("PointerEvent" in globalThis)) {
  // @ts-expect-error - jsdom does not implement pointer events; the charts only need the type.
  globalThis.PointerEvent = MouseEvent;
}
