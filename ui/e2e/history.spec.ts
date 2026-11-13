import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { chooseDark, stubDisplay } from "./display-helpers";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/history and /v1/items are stubbed.
// Not run by the agent (no browser in its sandbox); the human runs it. The browser date is pinned to
// Thursday, Nov 12, 2026, 3:30 PM local, so "today" is the same on every run.
const NOW = new Date(2026, 10, 12, 15, 30);
const at = (day: number, hour: number) => new Date(2026, 10, day, hour).toISOString();

const entry = (id: string, group: string, outcome: string, title: string, when: string, extra: Record<string, unknown> = {}) => ({
  item_id: id,
  source: "canvas",
  kind: "assignment",
  title,
  at: when,
  group,
  reopened: false,
  completed_by: group === "done_by_you" ? "user" : group === "done_by_source" ? "source" : null,
  outcome,
  note: null,
  link: null,
  ...extra,
});

type Entry = ReturnType<typeof entry>;
interface Day {
  day: string;
  done_by_you?: Entry[];
  done_by_source?: Entry[];
  dismissed?: Entry[];
  gone?: Entry[];
}

const days: Day[] = [
  {
    day: "2026-11-10",
    done_by_you: [entry("old", "done_by_you", "done", "Old essay", at(10, 9))],
    gone: [entry("gone1", "gone", "gone", "Vanished event", at(10, 12))],
  },
  {
    day: "2026-11-12",
    done_by_you: [entry("mine", "done_by_you", "done", "Lab report 4", at(12, 9), { note: "turned in late" })],
    done_by_source: [entry("theirs", "done_by_source", "done", "Quiz 3", at(12, 11))],
    dismissed: [entry("noise", "dismissed", "dismissed", "Newsletter", at(12, 13))],
  },
];

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
});

test("History shows days with rows, with privacy on, and has no axe violations in either theme", async ({ page }) => {
  await stubDisplay(page, { privacy_mode: true });
  await page.route("**/v1/history**", (route) => route.fulfill({ json: days }));
  await page.goto("/history");

  await expect(page.locator("html")).toHaveAttribute("data-privacy", "on");
  await expect(page.getByRole("heading", { level: 1, name: "History" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Thursday, Nov 12", "Tuesday, Nov 10"]);
  const entries = page.getByTestId("history-entry");
  await expect(entries).toHaveCount(5);
  await expect(entries.first()).toBeVisible();
  await expect(entries.first()).toContainText("Newsletter");
  await expect(entries.first()).toContainText("Dismissed");
  await expect(page.getByTestId("history-day").first()).toContainText("2 done, 1 dismissed");
  // The privacy mask is a blur on the sensitive text.
  const filter = await page.getByText("Lab report 4").evaluate((el) => getComputedStyle(el).filter);
  expect(filter).toContain("blur");

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await chooseDark(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(entries.first()).toBeVisible();
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});

test("filters and search narrow the loaded entries, and Restore shows only on today's own entries", async ({ page }) => {
  await stubDisplay(page);
  await page.route("**/v1/history**", (route) => route.fulfill({ json: days }));
  await page.goto("/history");
  const entries = page.getByTestId("history-entry");
  await expect(entries).toHaveCount(5);

  await expect(page.getByRole("button", { name: /^Restore/ })).toHaveText(["Restore", "Restore"]);
  await expect(entries.filter({ hasText: "Quiz 3" }).getByRole("button")).toHaveCount(0);
  await expect(entries.filter({ hasText: "Old essay" }).getByRole("button")).toHaveCount(0);
  await expect(entries.filter({ hasText: "Vanished event" }).getByRole("button")).toHaveCount(0);

  await page.getByRole("radio", { name: "Dismissed" }).check();
  await expect(entries).toHaveCount(1);
  await page.getByRole("radio", { name: "Done" }).check();
  await expect(entries).toHaveCount(3);
  await page.getByRole("radio", { name: "All" }).check();
  await page.getByRole("searchbox", { name: "Search" }).fill("late");
  await expect(entries).toHaveCount(1);
  await expect(entries.first()).toContainText("Lab report 4");
  await page.getByRole("searchbox", { name: "Search" }).fill("zzz");
  await expect(page.getByText("Nothing matches.")).toBeVisible();
});

test("Restore posts, announces, and the entry leaves after the refetch", async ({ page }) => {
  await stubDisplay(page);
  let current = days;
  const posts: string[] = [];
  await page.route("**/v1/history**", (route) => route.fulfill({ json: current }));
  await page.route("**/v1/items/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    posts.push(path);
    current = current.map((d) => ({ ...d, dismissed: (d.dismissed ?? []).filter((e) => e.item_id !== "noise") }));
    return route.fulfill({ json: { id: "noise" } });
  });
  await page.goto("/history");
  await page.getByRole("button", { name: "Restore Newsletter" }).click();
  await expect(page.getByTestId("toast")).toContainText("Restored.");
  await expect(page.getByTestId("history-entry")).toHaveCount(4);
  await expect.poll(() => posts).toEqual(["/v1/items/noise/restore"]);
});

test("empty and failing states use fixed messages, and Retry loads again", async ({ page }) => {
  await stubDisplay(page);
  await page.route("**/v1/history**", (route) => route.fulfill({ json: [] }));
  await page.goto("/history");
  await expect(page.getByText("Nothing done or dismissed in the last 30 days.")).toBeVisible();

  await page.unroute("**/v1/history**");
  await page.route("**/v1/history**", (route) => route.fulfill({ status: 500, json: { detail: "secret server text" } }));
  await page.reload();
  await expect(page.getByText("Could not load history. Try again.")).toBeVisible();
  await expect(page.getByText("secret server text")).toHaveCount(0);

  await page.unroute("**/v1/history**");
  await page.route("**/v1/history**", (route) => route.fulfill({ json: days }));
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByTestId("history-entry")).toHaveCount(5);
});
