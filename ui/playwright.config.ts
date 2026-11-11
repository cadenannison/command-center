import { defineConfig, devices } from "@playwright/test";

// One smoke test against the production build served by `vite preview` on loopback. The API is stubbed
// in the test (page.route), so no backend runs. `vite preview` sends no CSP header; the CSP of decision
// 0301 is the api layer's job and is not exercised here. The human installs the browser (playwright's
// own chromium download); agents never run that.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:4173", trace: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm exec vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
  },
});
