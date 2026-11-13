import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards and /v1/events are stubbed.
// Not run by the agent (no browser in its sandbox); the human runs it. The browser date is pinned to
// Thursday, Nov 12, 2026, 3:30 PM local, so Today, Now and Next are the same on every run.
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
    // Events: 7 wide (W3), 12 tall (H3).
    items: [{ id: "events-1", widgetId: "events", x: 0, y: 0, w: 7, h: 12, pinned: false, sources: ["cal"], options: {} }],
  },
};

const base = {
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: at(12, 14),
  has_note: false,
  user_id: "local",
};

const calendarEvent = (id: string, title: string, start: string, end: string, extra: Record<string, unknown> = {}) => ({
  ...base,
  id,
  kind: "event",
  source: "apple_calendar",
  title,
  start,
  end,
  ...extra,
});

const events = [
  calendarEvent("holiday", "Campus open day", new Date(2026, 10, 12).toISOString(), new Date(2026, 10, 13).toISOString()),
  calendarEvent("standup", "Standup", at(12, 9), at(12, 9, 30)),
  calendarEvent("class", "STAT 121 lecture", at(12, 15), at(12, 16), {
    link: "https://calendar.example.test/e/class",
    raw: { location: "Room 4" },
  }),
  calendarEvent("group", "Study group", at(12, 17), at(12, 18)),
  calendarEvent("dentist", "Dentist", at(13, 8, 30), at(13, 9, 30)),
  calendarEvent("lab", "CS 312 lab", at(16, 10), at(16, 12)),
  { ...base, id: "wx-12", kind: "weather", source: "weather", title: "High 58°, low 39°", start: at(12, 0), end: null },
];

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
  await page.route("**/v1/dashboards**", (route) => route.fulfill({ json: [dashboard] }));
  await page.route("**/v1/events**", (route) => route.fulfill({ json: events }));
});

test("the events widget shows its groups, rows, markers and link, with no axe violations in either theme", async ({ page }) => {
  await page.goto("/dashboard");

  const widget = page.getByTestId("widget-events-1");
  await expect(widget.getByRole("heading", { level: 2, name: "Events" })).toBeVisible();
  await expect(widget.getByRole("heading", { level: 3 })).toHaveText(["Today", "Tomorrow", "Mon, Nov 16"]);
  await expect(widget.getByTestId("event-row").first()).toBeVisible();
  await expect(widget.getByTestId("event-row").first()).toContainText("All day");

  const now = widget.locator('[data-marker="now"]');
  await expect(now).toContainText("STAT 121 lecture");
  await expect(now).toContainText("Room 4");
  await expect(now).toContainText("until 4:00 PM");
  await expect(widget.locator('[data-marker="next"]')).toContainText("Study group");

  const link = widget.getByRole("link", { name: "Open STAT 121 lecture in a new tab" });
  await expect(link).toHaveAttribute("href", "https://calendar.example.test/e/class");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");

  await link.focus();
  await expect(link).toBeFocused();
  await expect(link).toHaveCSS("outline-style", "solid");

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(widget.getByTestId("event-row").first()).toBeVisible();
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});

test("a failing events route shows a fixed message with Retry, and the dashboard stays", async ({ page }) => {
  await page.route("**/v1/events**", (route) => route.fulfill({ status: 500, json: { detail: "secret" } }));
  await page.goto("/dashboard");
  const widget = page.getByTestId("widget-events-1");
  await expect(widget.getByRole("alert")).toContainText("Could not load your events");
  await expect(widget.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByText("secret")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
});
