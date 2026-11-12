import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards is stubbed. Run by the human.
// The window is 1440 wide so the grid has 12 columns; one column is about 118px with the 14px gap.
const COLUMN_PX = 118;

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

const dashboard = (revision: number) => ({
  id: "main",
  name: "Main",
  position: 0,
  revision,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    items: [item("needs_me-1", "needs_me", 0, 7, ["cal"]), item("events-2", "events", 7, 5, ["cal"])],
  },
});

async function stubDashboards(page: Page): Promise<unknown[]> {
  const saved: unknown[] = [];
  await page.route("**/v1/dashboards**", async (route) => {
    const request = route.request();
    if (request.method() === "PUT") {
      saved.push(request.postDataJSON());
      await route.fulfill({ json: dashboard(2) });
      return;
    }
    await route.fulfill({ json: [dashboard(1)] });
  });
  return saved;
}

test.use({ viewport: { width: 1440, height: 900 } });

test("dragging a header moves the widget one column and saves it", async ({ page }) => {
  const saved = await stubDashboards(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Edit" }).click();

  const events = page.getByTestId("widget-events-2");
  await expect(events).toHaveAttribute("data-x", "7");
  const header = page.getByRole("button", { name: /^Events W\d/ });
  const box = await header.boundingBox();
  if (!box) throw new Error("no header box");
  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX - COLUMN_PX / 2, startY, { steps: 4 });
  await expect(page.getByTestId("drop-outline")).toBeVisible();
  await page.mouse.move(startX - COLUMN_PX, startY, { steps: 4 });
  await page.mouse.up();
  await expect(events).toHaveAttribute("data-x", "6");

  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  expect(JSON.stringify(saved[0])).toContain('"x":6');
});

test("dragging the corner resizes a widget", async ({ page }) => {
  await stubDashboards(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Edit" }).click();

  const needs = page.getByTestId("widget-needs_me-1");
  const corner = needs.getByTestId("handle-se");
  const box = await corner.boundingBox();
  if (!box) throw new Error("no corner box");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - COLUMN_PX, y, { steps: 6 });
  await page.mouse.up();
  await expect(needs).toHaveAttribute("data-w", "6");
});

test("a widget can be moved and resized from the keyboard, with announcements", async ({ page }) => {
  await stubDashboards(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Edit" }).click();

  const header = page.getByRole("button", { name: /^Events W\d/ });
  await header.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("live-region")).toContainText("Picked up Events");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("live-region")).toContainText("Events moved to column 7, row 1.");
  await page.keyboard.press("Shift+ArrowRight");
  await page.keyboard.press("Enter");
  await expect(header).toBeFocused();
  await expect(page.getByTestId("widget-events-2")).toHaveAttribute("data-x", "6");
});

test("the dashboard has no axe violations in either theme, with edit mode on", async ({ page }) => {
  await stubDashboards(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).click();

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});
