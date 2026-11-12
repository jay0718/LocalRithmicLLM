/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, Vite serves the UI and proxies each backend under one origin,
// so the browser needs no CORS configuration. Production uses the same paths.
const console_ = process.env.LRL_CONSOLE_URL ?? "http://127.0.0.1:8001";
const gex = process.env.LRL_GEX_URL ?? "http://127.0.0.1:8002";
const gateway = process.env.LRL_GATEWAY_URL ?? "http://127.0.0.1:8003";

const strip = (prefix: string) => (path: string) => path.slice(prefix.length) || "/";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/console": { target: console_, rewrite: strip("/api/console") },
      "/api/gex": { target: gex, rewrite: strip("/api/gex"), ws: true },
      "/api/gateway": { target: gateway, rewrite: strip("/api/gateway") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
