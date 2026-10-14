import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Rust API runs on 127.0.0.1:8787 (read-only). Proxy /api there so the
// browser talks to one origin and no token/secret ever touches the frontend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/health": "http://127.0.0.1:8787",
    },
  },
});
