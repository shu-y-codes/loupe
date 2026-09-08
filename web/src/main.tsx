/**
 * The entry point. One mount, no router.
 *
 * Overview | Review is a sidebar switch rather than a URL: two destinations that share a
 * store and a sidebar are page state, and a router would put a deep-link surface into v1
 * that nothing asked for (`specs/loupe-ui-design.md`, Navigation).
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./theme/tokens.css";

const container = document.getElementById("root");
if (!container) throw new Error("no #root to mount into");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
