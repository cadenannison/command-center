import { defineConfig } from "vitest/config";

// A run that finds no tests fails (passWithNoTests stays off): ui/.test-floor (decision 0303) backs this.
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    passWithNoTests: false,
    restoreMocks: true,
  },
});
