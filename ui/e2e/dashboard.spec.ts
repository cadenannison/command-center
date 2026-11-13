import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards is stubbed. Run by the human.
// The window is 1440 wide so the grid has 12 columns; one column is about 118px with the 14px gap.
const COLUMN_PX = 118;

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

const dashboard = (revision: number) => ({
  id: "main",
  name: "Main",
  position: 0,
  revision,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    items: [
      item("needs_me-1", "needs_me", 0, 7, ["cal"]),
      item("events-2", "events", 7, 5, ["cal"]),
      // Below the other two, so their positions are unchanged. Wide and tall enough for W3 and H3.
      item("tasks-3", "tasks", 0, 8, ["canvas", "ls", "manual"], 10),
    ],
  },
});

const HOUR = 3_600_000;
const task = (id: string, title: string, dueOffsetMs: number | null, link: string | null, priority: number) => ({
  id,
  title,
  source: "canvas",
  due: dueOffsetMs === null ? null : new Date(Date.now() + dueOffsetMs).toISOString(),
  link,
  done: false,
  priority,
  reasons: [
    { code: "due_soon", text: "Due soon", points: 4 },
    { code: "canvas", text: "From Canvas", points: 2 },
  ],
});

/** GET /v1/tasks: one open task in each group, one with an http link and the rest with a null link. */
async function stubTasks(page: Page): Promise<void> {
  await page.route("**/v1/tasks**", async (route) => {
    await route.fulfill({
      json: [
        task("t1", "Overdue lab report", -3 * HOUR, "https://canvas.example.edu/courses/1/assignments/1", 9),
        task("t2", "Read chapter 4", 10 * HOUR, null, 6),
        task("t3", "Group project", 120 * HOUR, null, 3),
        task("t4", "Buy a notebook", null, null, 1),
      ],
    });
  });
}

async function stubDashboards(page: Page): Promise<unknown[]> {
  const saved: unknown[] = [];
  await stubTasks(page);
  // The Events widget and the Summary card read these; stubbed so edit-mode axe sees them with data, not an unmocked route.
  await page.route("**/v1/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) =>
    route.fulfill({
      json: {
        summary: { headline: "Two deadlines today", priorities: ["Finish the lab report"], heads_up: ["Quiz on Friday"] },
        provider: "gemini",
        cached: true,
      },
    }),
  );
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
  const header = page.getByRole("button", { name: /^Move Events, W\d/ });
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
  // The Summary card above the grid pushes this corner below the 900px window; mouse events outside the viewport do nothing.
  await corner.scrollIntoViewIfNeeded();
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

  const header = page.getByRole("button", { name: /^Move Events, W\d/ });
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
  // Rows are visible: one per group, so axe sees the pills, the disclosure buttons, the link and the group headings.
  const tasks = page.getByTestId("widget-tasks-3");
  await expect(tasks.getByRole("button", { name: "Overdue lab report" })).toBeVisible();
  await expect(tasks.getByRole("link", { name: "Open Overdue lab report in a new tab" })).toBeVisible();
  await expect(tasks.getByRole("heading", { level: 3, name: "No due date" })).toBeVisible();
  await tasks.getByRole("button", { name: "Read chapter 4" }).click();
  await expect(tasks.getByText("From Canvas")).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Tasks" })).toBeVisible();

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});
