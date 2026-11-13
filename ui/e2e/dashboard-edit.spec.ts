import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { chooseDark, stubDisplay } from "./display-helpers";

// Edit-mode tools (card E1). Needs `pnpm run build` first (the web server is `vite preview`). /v1 is stubbed. Run by the human.
// The window is 1440 wide so the grid has 12 columns and editing is on.

const item = (id: string, widgetId: string, x: number, w: number, sources: string[], y = 0) => ({
  id,
  widgetId,
  x,
  y,
  w,
  h: 10,
  pinned: false,
  sources,
  options: {},
});

const layout = {
  version: 1,
  items: [
    item("needs_me-1", "needs_me", 0, 7, ["cal"]),
    item("events-2", "events", 7, 5, ["cal"]),
    item("tasks-3", "tasks", 0, 8, ["canvas", "ls", "manual"], 10),
  ],
};

const dashboard = (revision: number) => ({
  id: "main",
  name: "Main",
  position: 0,
  revision,
  updated_at: "2026-11-12T10:00:00Z",
  layout,
});

async function stubApi(page: Page): Promise<unknown[]> {
  const saved: unknown[] = [];
  await stubDisplay(page);
  await page.route("**/v1/tasks**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) =>
    route.fulfill({
      json: { summary: { headline: "A quiet day", priorities: [], heads_up: [] }, provider: "gemini", cached: true },
    }),
  );
  await page.route("**/v1/dashboards**", async (route) => {
    const request = route.request();
    if (request.method() === "PUT") {
      saved.push(request.postDataJSON());
      await route.fulfill({ json: dashboard(saved.length + 1) });
      return;
    }
    await route.fulfill({ json: [dashboard(1)] });
  });
  return saved;
}

async function startEditing(page: Page): Promise<unknown[]> {
  const saved = await stubApi(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("group", { name: "Edit tools" })).toBeVisible();
  return saved;
}

test.use({ viewport: { width: 1440, height: 900 } });

test("a widget is added from the gallery, announced, focus returns to Add widget, and it saves", async ({ page }) => {
  const saved = await startEditing(page);
  await page.getByRole("button", { name: "Add widget" }).click();
  const gallery = page.getByRole("dialog", { name: "Add a widget" });
  await expect(gallery).toBeVisible();
  await gallery.getByRole("button", { name: "Add Weather" }).click();

  await expect(gallery).toBeHidden();
  await expect(page.getByTestId("widget-weather-1")).toHaveAttribute("data-y", "20");
  await expect(page.getByTestId("live-region")).toContainText("Added Weather");
  await expect(page.getByRole("button", { name: "Add widget" })).toBeFocused();

  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  expect(JSON.stringify(saved[0])).toContain('"widgetId":"weather"');
});

test("Escape closes the gallery without adding and focus returns to Add widget", async ({ page }) => {
  await startEditing(page);
  await page.getByRole("button", { name: "Add widget" }).click();
  await expect(page.getByRole("dialog", { name: "Add a widget" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("button", { name: "Add widget" })).toBeFocused();
  await expect(page.getByTestId("widget-weather-1")).toHaveCount(0);
});

test("a widget is removed from its menu, and Undo and Redo bring it back and take it away", async ({ page }) => {
  await startEditing(page);
  await page.getByRole("button", { name: "Options for Events" }).click();
  await page.getByRole("menuitem", { name: "Remove" }).click();
  await expect(page.getByTestId("widget-events-2")).toHaveCount(0);
  await expect(page.getByTestId("live-region")).toContainText("Events removed");

  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await expect(page.getByRole("button", { name: "Undo" })).toBeDisabled();

  await page.getByRole("button", { name: "Redo" }).click();
  await expect(page.getByTestId("widget-events-2")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Redo" })).toBeDisabled();
});

test("the S size preset resizes a widget to 3 by 5", async ({ page }) => {
  await startEditing(page);
  await page.getByRole("button", { name: "Options for Events" }).click();
  await page.getByRole("menuitem", { name: /^S ·/ }).click();
  const events = page.getByTestId("widget-events-2");
  await expect(events).toHaveAttribute("data-w", "3");
  await expect(events).toHaveAttribute("data-h", "5");
  await expect(page.getByTestId("live-region")).toContainText("Events resized to 3×5.");
});

test("Export downloads the stored layout document under the dashboard's name", async ({ page }) => {
  await startEditing(page);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export" }).click()]);
  expect(download.suggestedFilename()).toBe("command-center-Main-layout.json");
  const path = await download.path();
  const doc = JSON.parse(await readFile(path, "utf8")) as { version: number; items: unknown[] };
  expect(Object.keys(doc)).toEqual(["version", "items"]);
  expect(doc).toEqual(layout);
});

async function axeClean(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
}

async function checkSurfaces(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Add widget" }).click();
  await expect(page.getByRole("dialog", { name: "Add a widget" })).toBeVisible();
  await axeClean(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();

  await page.getByRole("button", { name: "Reset" }).click();
  await expect(page.getByRole("dialog", { name: "Reset this dashboard" })).toBeVisible();
  await axeClean(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();

  await page.getByRole("button", { name: "Options for Events" }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await axeClean(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toBeHidden();
}

test("edit mode, the gallery, the reset confirm and the widget menu have no axe violations in either theme", async ({ page }) => {
  await startEditing(page);
  await expect(page.getByRole("heading", { level: 2, name: "Tasks" })).toBeVisible();
  await axeClean(page);
  await checkSurfaces(page);

  await chooseDark(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await axeClean(page);
  await checkSurfaces(page);
});
