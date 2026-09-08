/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two processes in development, one origin as far as the browser is concerned: Vite serves
// the app and proxies `/v1` to uvicorn, so the client can call relative paths and no CORS
// policy has to be written, maintained, or accidentally widened. In production FastAPI
// serves `dist/` at `/` and the same relative paths hit the same server
// (`specs/api-contract.md` §4.4).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: process.env.LOUPE_API_ORIGIN ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    // `loupe.api.app._mount_web` serves exactly this directory.
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
