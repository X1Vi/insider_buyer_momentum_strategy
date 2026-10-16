import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Rust API runs on 127.0.0.1:8787 (read-only). Proxy /api there so the
// browser talks to one origin and no token/secret ever touches the frontend.
export default defineConfig({
  plugins: [react()],
  server: {
    // Listen on every interface so other machines on the LAN can reach the UI.
    // The run script overrides this with --host (set INSIDER_FRONTEND_HOST=127.0.0.1
    // to keep it local-only).
    host: true,
    // Dev server accepts requests addressed to this machine's IP / hostname.
    allowedHosts: true,
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/health": "http://127.0.0.1:8787",
    },
  },
});
