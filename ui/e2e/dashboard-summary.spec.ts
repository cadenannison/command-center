import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";
import { chooseDark, stubDisplay } from "./display-helpers";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards, /v1/events and /v1/summary are
// stubbed. Not run by the agent (no browser in its sandbox); the human runs it. The browser date is pinned.
const NOW = new Date(2026, 10, 12, 15, 30);

const dashboard = {
  id: "main",
  name: "Main",
  position: 0,
  revision: 1,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    items: [{ id: "events-1", widgetId: "events", x: 0, y: 0, w: 7, h: 10, pinned: false, sources: ["cal"], options: {} }],
  },
};

const summary = (provider: string) => ({
  summary: {
    headline: "Two deadlines today",
    priorities: ["Finish the lab report", "Read chapter 4", "Email the TA", "Book the study room", "Buy a notebook", "Water the plants"],
    heads_up: ["Quiz on Friday", "Overdue: Group project outline"],
  },
  provider,
  cached: false,
});

test.use({ viewport: { width: 1440, height: 900 } });

async function stub(page: Page, summaryRoute: (route: Route) => Promise<void>): Promise<string[]> {
  const requests: string[] = [];
  await stubDisplay(page);
  await page.clock.setFixedTime(NOW);
  await page.route("**/v1/dashboards**", (route) => route.fulfill({ json: [dashboard] }));
  await page.route("**/v1/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) => {
    requests.push(route.request().url());
    return summaryRoute(route);
  });
  return requests;
}

async function noAxeViolationsInBothThemes(page: Page, visible: () => Promise<void>) {
  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);
  await chooseDark(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await visible();
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
}

test("on: shows the headline, priorities, heads-up and who wrote it, asks once for the local day, no axe violations", async ({ page }) => {
  const requests = await stub(page, (route) => route.fulfill({ json: summary("gemini") }));
  await page.goto("/dashboard");
  const card = page.getByRole("region", { name: "Summary" });
  await expect(card.getByText("Two deadlines today")).toBeVisible();
  await expect(card.getByText("Finish the lab report")).toBeVisible();
  await expect(card.getByTestId("summary-more")).toHaveText("+1 more");
  await expect(card.getByText("Quiz on Friday")).toBeVisible();
  await expect(card.getByTestId("summary-caption")).toContainText("Written by Gemini.");
  await expect(card.getByTestId("summary-caption")).toContainText("Notes and email bodies are never sent.");
  expect(requests).toHaveLength(1);
  expect(new URL(requests[0] ?? "").searchParams.get("date")).toBe("2026-11-12");

  const toggle = card.getByRole("button", { name: "Collapse summary" });
  await toggle.focus();
  await expect(toggle).toHaveCSS("outline-style", "solid");
  await noAxeViolationsInBothThemes(page, () => expect(card.getByText("Two deadlines today")).toBeVisible());
});

test("collapse keeps the headline only, and the card stays in edit mode", async ({ page }) => {
  await stub(page, (route) => route.fulfill({ json: summary("gemini") }));
  await page.goto("/dashboard");
  const card = page.getByRole("region", { name: "Summary" });
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Collapse summary" }).click();
  await expect(card.getByText("Two deadlines today")).toBeVisible();
  await expect(card.getByText("Finish the lab report")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Expand summary" })).toHaveAttribute("aria-expanded", "false");
});

test("off (404): says Summaries are off and that Settings turns them on, with no axe violations", async ({ page }) => {
  await stub(page, (route) => route.fulfill({ status: 404, json: { detail: "Summaries are off" } }));
  await page.goto("/dashboard");
  const card = page.getByRole("region", { name: "Summary" });
  await expect(card.getByText("Summaries are off")).toBeVisible();
  await expect(card.getByText("They can be turned on in Settings.")).toBeVisible();
  await expect(card.getByRole("alert")).toHaveCount(0);
  await noAxeViolationsInBothThemes(page, () => expect(card.getByText("Summaries are off")).toBeVisible());
});

test("a failing route shows fixed text and Retry, never the server's text", async ({ page }) => {
  await stub(page, (route) => route.fulfill({ status: 500, json: { detail: "secret" } }));
  await page.goto("/dashboard");
  const card = page.getByRole("region", { name: "Summary" });
  await expect(card.getByRole("alert")).toContainText("Could not load the summary. Try again.");
  await expect(card.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByText("secret")).toHaveCount(0);
});

for (const [provider, notice] of [
  ["stored", "Showing an earlier summary"],
  ["template", "Showing a basic summary"],
] as const) {
  test(`${provider}: shows "${notice}" with the content, no axe violations`, async ({ page }) => {
    await stub(page, (route) => route.fulfill({ json: summary(provider) }));
    await page.goto("/dashboard");
    const card = page.getByRole("region", { name: "Summary" });
    await expect(card.getByTestId("summary-notice")).toHaveText(notice);
    await expect(card.getByText("Two deadlines today")).toBeVisible();
    await expect(card.getByTestId("summary-caption")).toHaveCount(0);
    await noAxeViolationsInBothThemes(page, () => expect(card.getByTestId("summary-notice")).toBeVisible());
  });
}
