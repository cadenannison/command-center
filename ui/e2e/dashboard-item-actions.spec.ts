import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { stubDisplay } from "./display-helpers";

// Needs `pnpm run build` first (the web server is `vite preview`). Every /v1 route is stubbed with page.route.
// Not run by the agent (no browser in its sandbox); the human runs it. The browser date is pinned to
// Thursday, Nov 12, 2026, 3:30 PM local.
const NOW = new Date(2026, 10, 12, 15, 30);
const at = (day: number, hour: number) => new Date(2026, 10, day, hour).toISOString();

const dashboard = {
  id: "main",
  name: "Main",
  position: 0,
  revision: 1,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    items: [{ id: "needs_me-1", widgetId: "needs_me", x: 0, y: 0, w: 7, h: 12, pinned: false, sources: ["cal", "canvas", "ls", "gmail", "manual"], options: {} }],
  },
};

const reasons = [{ code: "overdue", text: "Past its due time", points: 5 }];
const items = [
  { id: "n1", kind: "assignment", title: "Lab report 4", source: "canvas", at: at(12, 9), link: null, priority: 9, reasons },
  { id: "n2", kind: "email", title: "Reply to Dr. Lee", source: "gmail", at: at(13, 10), link: null, priority: 8, reasons },
];

interface Post {
  readonly path: string;
  readonly body: unknown;
}

/** /v1/needs-me hides what was dismissed, snoozed or done and shows it again after a restore; every POST is recorded. */
async function stubItems(page: Page): Promise<Post[]> {
  const hidden = new Set<string>();
  const posts: Post[] = [];
  await page.route("**/v1/dashboards**", (route) => route.fulfill({ json: [dashboard] }));
  await page.route("**/v1/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) =>
    route.fulfill({ json: { summary: { headline: "Busy day", priorities: [], heads_up: [] }, provider: "gemini", cached: true } }),
  );
  await page.route("**/v1/needs-me**", (route) => route.fulfill({ json: items.filter((i) => !hidden.has(i.id)) }));
  await page.route("**/v1/items/**", async (route) => {
    const url = new URL(route.request().url());
    const match = /\/v1\/items\/([^/]+)\/(done|dismiss|snooze|restore)$/.exec(url.pathname);
    if (!match?.[1] || !match[2]) return route.fulfill({ status: 404, json: { detail: "no" } });
    posts.push({ path: url.pathname, body: route.request().postDataJSON() as unknown });
    if (match[2] === "restore") hidden.delete(match[1]);
    else hidden.add(match[1]);
    return route.fulfill({ json: { id: match[1] } });
  });
  return posts;
}

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
  await stubDisplay(page);
});

test("Dismiss removes the row, shows the toast, and Undo brings the row back", async ({ page }) => {
  const posts = await stubItems(page);
  await page.goto("/dashboard");
  const widget = page.getByTestId("widget-needs_me-1");
  const rows = widget.getByTestId("needs-me-row");
  await expect(rows).toHaveCount(2);

  await widget.getByRole("button", { name: "Lab report 4" }).click();
  await widget.getByRole("button", { name: "Dismiss" }).click();

  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Reply to Dr. Lee");
  const toast = page.getByTestId("toast");
  await expect(toast).toBeVisible();
  await expect(toast).toContainText("Dismissed.");
  await expect.poll(() => posts.map((p) => p.path)).toEqual(["/v1/items/n1/dismiss"]);

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Lab report 4");
  // Undo closed the "Dismissed." toast. The restore raises its own plain confirmation (decision 0402): a status
  // message with no Undo of its own, which closes by itself after TOAST_MS (asserted with fake timers in toast.test.tsx).
  await expect(toast).toContainText("Restored.");
  await expect(toast).not.toContainText("Dismissed.");
  await expect(toast.getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Restored." })).toHaveCount(1);
  await expect.poll(() => posts.map((p) => p.path)).toEqual(["/v1/items/n1/dismiss", "/v1/items/n1/restore"]);
});

test("Snooze opens a menu of three presets inside main, posts the preset, and Undo restores", async ({ page }) => {
  const posts = await stubItems(page);
  await page.goto("/dashboard");
  const widget = page.getByTestId("widget-needs_me-1");
  const rows = widget.getByTestId("needs-me-row");
  await expect(rows).toHaveCount(2);

  await widget.getByRole("button", { name: "Reply to Dr. Lee" }).click();
  await widget.getByRole("button", { name: "Snooze" }).click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  await expect(page.locator("main").getByRole("menu")).toHaveCount(1);
  await expect(menu.getByRole("menuitem")).toHaveText(["Later today", "Tomorrow morning", "Next week"]);
  // Non-modal: the page behind it is still there for assistive tech and the mouse.
  await expect(page.getByRole("heading", { level: 2, name: "Needs me" })).toBeVisible();

  await menu.getByRole("menuitem", { name: "Tomorrow morning" }).click();
  await expect(rows).toHaveCount(1);
  await expect(page.getByTestId("toast")).toContainText("Snoozed until tomorrow morning.");
  await expect.poll(() => posts.at(-1)).toEqual({ path: "/v1/items/n2/snooze", body: { preset: "tomorrow_morning" } });

  await page.getByTestId("toast").getByRole("button", { name: "Undo" }).click();
  await expect(rows).toHaveCount(2);
  await expect.poll(() => posts.at(-1)?.path).toBe("/v1/items/n2/restore");
});

test("Done is keyboard reachable: the toast takes focus and Undo works from the keyboard", async ({ page }) => {
  const posts = await stubItems(page);
  await page.goto("/dashboard");
  const widget = page.getByTestId("widget-needs_me-1");
  await widget.getByRole("button", { name: "Lab report 4" }).focus();
  await page.keyboard.press("Enter");
  await widget.getByRole("button", { name: "Done" }).focus();
  await page.keyboard.press("Enter");
  const undo = page.getByTestId("toast").getByRole("button", { name: "Undo" });
  await expect(undo).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => posts.map((p) => p.path)).toEqual(["/v1/items/n1/done", "/v1/items/n1/restore"]);
  await expect(widget.getByTestId("needs-me-row")).toHaveCount(2);
});

test("a failing action shows a fixed message and keeps the row", async ({ page }) => {
  await stubItems(page);
  await page.route("**/v1/items/**", (route) => route.fulfill({ status: 500, json: { detail: "secret server text" } }));
  await page.goto("/dashboard");
  const widget = page.getByTestId("widget-needs_me-1");
  await widget.getByRole("button", { name: "Lab report 4" }).click();
  await widget.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByTestId("toast")).toContainText("Could not dismiss it. Try again.");
  await expect(page.getByText("secret server text")).toHaveCount(0);
  await expect(widget.getByTestId("needs-me-row")).toHaveCount(2);
});
