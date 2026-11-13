import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { chooseDark, stubDisplay } from "./display-helpers";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards and /v1/events are stubbed.
// Not run by the agent (no browser in its sandbox); the human runs it. The browser date is pinned to
// Thursday, Nov 12, 2026, 3:30 PM local, so the week and the forecast are the same on every run.
const NOW = new Date(2026, 10, 12, 15, 30);
const at = (day: number, hour: number, minute = 0) => new Date(2026, 10, day, hour, minute).toISOString();

const item = (id: string, widgetId: string, x: number, w: number, h: number, sources: string[], y = 0) => ({
  id,
  widgetId,
  x,
  y,
  w,
  h,
  pinned: false,
  sources,
  options: {},
});

const dashboard = {
  id: "main",
  name: "Main",
  position: 0,
  revision: 1,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    items: [
      // Week: 7 wide (W3), 8 tall (H3). Weather: 5 wide (W3), 8 tall (H3).
      item("week-1", "week", 0, 7, 8, ["cal"]),
      item("weather-2", "weather", 7, 5, 8, ["wx"]),
    ],
  },
};

const base = {
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: at(12, 14),
  has_note: false,
  user_id: "local",
};

const calendarEvent = (id: string, title: string, start: string, end: string) => ({
  ...base,
  id,
  kind: "event",
  source: "apple_calendar",
  title,
  start,
  end,
});

const weatherDay = (day: number, high: number, low: number, rain: number) => ({
  ...base,
  id: `wx-${String(day)}`,
  kind: "weather",
  source: "weather",
  title: `High ${String(high)}°, low ${String(low)}°, ${String(rain)}% rain`,
  start: at(day, 0),
  raw: { high_f: high, low_f: low, rain_percent: rain },
});

/** One route serves both widgets: the week widget ignores weather items and the weather widget ignores events. */
async function stubApi(page: Page): Promise<void> {
  await stubDisplay(page);
  await page.clock.setFixedTime(NOW);
  await page.route("**/v1/dashboards**", (route) => route.fulfill({ json: [dashboard] }));
  await page.route("**/v1/events**", (route) =>
    route.fulfill({
      json: [
        calendarEvent("e1", "Standup", at(10, 9), at(10, 9, 30)),
        calendarEvent("e2", "Study group", at(12, 17), at(12, 18)),
        calendarEvent("e3", "Office hours", at(12, 19), at(12, 20)),
        calendarEvent("e4", "Dentist", at(13, 8), at(13, 9)),
        weatherDay(12, 58, 39, 20),
        weatherDay(13, 52, 36, 0),
        weatherDay(14, 47, 33, 60),
        weatherDay(15, 45, 30, 10),
      ],
    }),
  );
}

test.use({ viewport: { width: 1440, height: 900 } });

test("the week and weather widgets show their rows and have no axe violations in either theme", async ({ page }) => {
  await stubApi(page);
  await page.goto("/dashboard");

  const week = page.getByTestId("widget-week-1");
  await expect(week.getByRole("heading", { level: 2, name: "This week" })).toBeVisible();
  await expect(week.getByTestId("week-day")).toHaveCount(7);
  await expect(week.getByLabel("Thursday, November 12, today: 2 events")).toBeVisible();
  await expect(week.getByTestId("week-next")).toContainText("Next: Study group, Today 5:00 PM");
  await expect(week.getByTestId("week-item").first()).toBeVisible();

  const weather = page.getByTestId("widget-weather-2");
  await expect(weather.getByRole("heading", { level: 2, name: "Weather" })).toBeVisible();
  await expect(weather.getByTestId("weather-high")).toContainText("58°");
  await expect(weather.getByTestId("weather-day").first()).toBeVisible();

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await chooseDark(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});

test("a failing events route leaves both widgets with a retry, and the dashboard stays", async ({ page }) => {
  await stubApi(page);
  await page.route("**/v1/events**", (route) => route.fulfill({ status: 500, json: { detail: "secret" } }));
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-week-1").getByRole("alert")).toContainText("Could not load your week");
  await expect(page.getByTestId("widget-weather-2").getByRole("alert")).toContainText("Could not load the forecast");
  await expect(page.getByText("secret")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
});
