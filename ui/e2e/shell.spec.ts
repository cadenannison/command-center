import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { chooseDark, stubDisplay } from "./display-helpers";

// Needs `pnpm run build` first (the web server is `vite preview`). The API is stubbed. Run by the human.

const item = (id: string, widgetId: string, x: number, w: number, sources: string[]) => ({
  id,
  widgetId,
  x,
  y: 0,
  w,
  h: 10,
  pinned: false,
  sources,
  options: {},
});

async function stubDashboard(page: Page): Promise<void> {
  await page.route("**/v1/dashboards**", (route) =>
    route.fulfill({
      json: [
        {
          id: "main",
          name: "Main",
          position: 0,
          revision: 1,
          updated_at: "2026-11-12T10:00:00Z",
          layout: { version: 1, items: [item("needs_me-1", "needs_me", 0, 7, ["cal"]), item("events-2", "events", 7, 5, ["cal"])] },
        },
      ],
    }),
  );
  await page.route("**/v1/events**", (route) =>
    route.fulfill({
      json: [
        {
          id: "e1",
          kind: "event",
          source: "apple_calendar",
          title: "Dentist with Dr Lee",
          start: new Date().toISOString(),
          end: new Date(Date.now() + 3_600_000).toISOString(),
          due: null,
          status: null,
          urgency: 0,
          priority: null,
          fetched_at: "2026-11-12T10:00:00Z",
          has_note: false,
          user_id: "local",
          raw: { location: "Room 4" },
        },
      ],
    }),
  );
  await page.route("**/v1/needs-me**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/tasks**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) =>
    route.fulfill({
      json: {
        summary: { headline: "Call Sam about rent", priorities: ["Email Priya"], heads_up: [] },
        provider: "gemini",
        cached: true,
      },
    }),
  );
}

test("the rail navigates between routes and marks the active one", async ({ page }) => {
  await stubDisplay(page);
  await stubDashboard(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  const rail = page.getByRole("navigation", { name: "Main" });
  await expect(rail.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
  for (const name of ["Chat", "History", "Focus", "Settings"]) {
    await rail.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(rail.getByRole("link", { name })).toHaveAttribute("aria-current", "page");
  }
  await expect(rail.getByText(/design rules/i)).toHaveCount(0);
  await page.goto("/no-such-page");
  await page.getByRole("link", { name: "Back to Today" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("the rail collapses, keeps its names, and remembers it after a reload", async ({ page }) => {
  await stubDisplay(page);
  await page.goto("/chat");
  const toggle = page.getByRole("button", { name: "Menu" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await page.reload();
  await expect(page.getByRole("button", { name: "Menu" })).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("link", { name: "History" })).toBeVisible();
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

test("privacy mask blurs sensitive text, lifts on hover, and passes axe in both themes", async ({ page }) => {
  const display = await stubDisplay(page);
  await stubDashboard(page);
  await page.goto("/dashboard");
  const title = page.getByText("Dentist with Dr Lee");
  await expect(title).toBeVisible();
  const privacy = page.getByRole("button", { name: "Privacy" });
  await privacy.click();
  await expect(privacy).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("html")).toHaveAttribute("data-privacy", "on");
  await expect.poll(() => display.puts.at(-1)?.["privacy_mode"]).toBe(true);

  const blurred = (loc: ReturnType<Page["locator"]>) => loc.evaluate((el) => getComputedStyle(el).filter);
  expect(await blurred(title)).toContain("blur");
  // Times are not marked.
  await title.hover();
  expect(await blurred(title)).toBe("none");
  await page.mouse.move(0, 0);

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);
  await chooseDark(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("html")).toHaveAttribute("data-privacy", "on");
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});

test("the dashboard renders inside the shell with one banner, one nav and one main", async ({ page }) => {
  await stubDisplay(page);
  await stubDashboard(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await expect(page.getByRole("banner")).toHaveCount(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(1);
  // The Display popover opens from the titlebar and lands inside <main>.
  await page.getByRole("button", { name: "Display", exact: true }).click();
  await expect(page.getByRole("main").getByRole("dialog", { name: "Display settings" })).toBeVisible();
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});
