import { defineConfig } from "vitest/config";

// The test zone is set once, here, before any worker starts (it has DST, which the day-boundary tests need).
// Tests that are zone-sensitive still assert it took effect.
process.env["TZ"] = "America/Denver";

// A run that finds no tests fails (passWithNoTests stays off): ui/.test-floor (decision 0303) backs this.
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    passWithNoTests: false,
    restoreMocks: true,
    setupFiles: ["src/test/setup.ts"],
  },
});
