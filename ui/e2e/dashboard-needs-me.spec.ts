import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards and /v1/needs-me are stubbed.
// Not run by the agent (no browser in its sandbox); the human runs it. The browser date is pinned to
// Thursday, Nov 12, 2026, 3:30 PM local, so "Now", "Overdue" and the times are the same on every run.
const NOW = new Date(2026, 10, 12, 15, 30);
const at = (day: number, hour: number, minute = 0) => new Date(2026, 10, day, hour, minute).toISOString();

const dashboard = {
  id: "main",
  name: "Main",
  position: 0,
  revision: 1,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    // Needs me: 7 wide (W3), 12 tall (H3).
    items: [{ id: "needs_me-1", widgetId: "needs_me", x: 0, y: 0, w: 7, h: 12, pinned: false, sources: ["cal", "canvas", "ls", "gmail", "manual"], options: {} }],
  },
};

const reasons = [
  { code: "overdue", text: "Past its due time", points: 5 },
  { code: "canvas", text: "From Canvas", points: 2 },
];

// The server's order, not the time order: the widget must show it as sent.
const items = [
  { id: "n1", kind: "assignment", title: "Lab report 4", source: "canvas", at: at(12, 9), link: "https://canvas.example.test/a/4", priority: 9, reasons },
  { id: "n2", kind: "email", title: "Reply to Dr. Lee", source: "gmail", at: at(13, 10), link: null, priority: 8, reasons },
  { id: "n3", kind: "event", title: "STAT 121 lecture", source: "apple_calendar", at: at(12, 15), link: null, priority: 6, reasons },
  { id: "n4", kind: "event", title: "Study group", source: "apple_calendar", at: at(12, 17, 30), link: null, priority: 5, reasons },
  { id: "n5", kind: "task", title: "Buy a gift", source: "local", at: at(12, 16), link: null, priority: 5, reasons },
];

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
  await page.route("**/v1/dashboards**", (route) => route.fulfill({ json: [dashboard] }));
  await page.route("**/v1/needs-me**", (route) => route.fulfill({ json: items }));
  await page.route("**/v1/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) =>
    route.fulfill({ json: { summary: { headline: "Busy day", priorities: [], heads_up: [] }, provider: "gemini", cached: true } }),
  );
});

test("the Needs me widget shows ranked rows with kind and time, and has no axe violations in either theme", async ({ page }) => {
  await page.goto("/dashboard");

  const widget = page.getByTestId("widget-needs_me-1");
  await expect(widget.getByRole("heading", { level: 2, name: "Needs me" })).toBeVisible();
  const rows = widget.getByTestId("needs-me-row");
  await expect(rows).toHaveCount(5);
  await expect(rows.first()).toBeVisible();
  await expect(rows.first()).toContainText("Lab report 4");
  await expect(rows.first()).toContainText("Assignment");
  await expect(rows.first()).toContainText("Overdue");
  await expect(rows.nth(1)).toContainText("Reply");
  await expect(rows.nth(1)).toContainText("Due Tomorrow 10:00 AM");
  await expect(rows.nth(2)).toContainText("Now");
  await expect(rows.nth(3)).toContainText("Starts 5:30 PM");
  await expect(rows.first().locator("[data-priority]")).toContainText("Priority 9");

  const link = widget.getByRole("link", { name: "Open Lab report 4 in a new tab" });
  await expect(link).toHaveAttribute("href", "https://canvas.example.test/a/4");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");

  const toggle = rows.first().getByRole("button", { name: "Lab report 4" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(rows.first()).toContainText("Past its due time");
  await expect(rows.first()).toContainText("+5 points");

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(rows.first()).toBeVisible();
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});

test("an empty list says nothing needs you, and a failing route shows a fixed message with Retry", async ({ page }) => {
  await page.route("**/v1/needs-me**", (route) => route.fulfill({ json: [] }));
  await page.goto("/dashboard");
  const widget = page.getByTestId("widget-needs_me-1");
  await expect(widget).toContainText("Nothing needs you right now");

  await page.route("**/v1/needs-me**", (route) => route.fulfill({ status: 500, json: { detail: "secret" } }));
  await page.reload();
  await expect(widget.getByRole("alert")).toContainText("Could not load what needs you");
  await expect(widget.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByText("secret")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
});
