import { describe, expect, it } from "vitest";

// vitest.config.ts sets TZ once. The day-boundary and DST tests depend on it, so this proves it took effect.
describe("the test timezone", () => {
  it("is America/Denver, with DST", () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe("America/Denver");
    expect(new Date(2026, 10, 12, 12).getTimezoneOffset()).toBe(420); // MST in November
    expect(new Date(2026, 6, 1, 12).getTimezoneOffset()).toBe(360); // MDT in July
  });
});
