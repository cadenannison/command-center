import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server only (decision 0301 item 8): loopback host, explicit allowed hosts, no CORS. The API is
// reached same-origin through this proxy, so the browser never talks to another origin. The built files
// are served by FastAPI on the same origin (decision 0300), so no URL or credential is baked in.
const API_TARGET = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    allowedHosts: ["localhost", "127.0.0.1"],
    cors: false,
    proxy: {
      "/v1": { target: API_TARGET, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
