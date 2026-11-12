import { defineConfig, devices } from "@playwright/test";

// The gallery route exists only under the Vite dev server (decision 0342), so this config starts it on its
// own loopback port instead of `vite preview`. The human runs it by hand with:
//   playwright test -c playwright.gallery.config.ts   (from ui/, through pnpm)
export default defineConfig({
  testDir: "e2e-gallery",
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5174", trace: "off", reducedMotion: "reduce" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "vite --host 127.0.0.1 --port 5174 --strictPort",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: !process.env["CI"],
  },
});
