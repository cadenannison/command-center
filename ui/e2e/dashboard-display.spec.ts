import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { closeDisplay, openDisplay, stubDisplay } from "./display-helpers";

// Needs `pnpm run build` first (the web server is `vite preview`). /v1/dashboards, /v1/display-settings and the widgets'
// routes are stubbed. Not run by the agent (no browser in its sandbox); the human runs it.
const dashboard = {
  id: "main",
  name: "Main",
  position: 0,
  revision: 1,
  updated_at: "2026-11-12T10:00:00Z",
  layout: {
    version: 1,
    items: [
      { id: "needs_me-1", widgetId: "needs_me", x: 0, y: 0, w: 7, h: 10, pinned: false, sources: ["cal"], options: {} },
      { id: "events-2", widgetId: "events", x: 7, y: 0, w: 5, h: 10, pinned: false, sources: ["cal"], options: {} },
    ],
  },
};

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ page }) => {
  await page.route("**/v1/dashboards**", (route) => route.fulfill({ json: [dashboard] }));
  await page.route("**/v1/needs-me**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/v1/summary**", (route) =>
    route.fulfill({ json: { summary: { headline: "A quiet day", priorities: [], heads_up: [] }, provider: "gemini", cached: true } }),
  );
});

/** No horizontal overflow: documentElement.scrollWidth <= clientWidth. The grid changes its column tier after a
 *  resize, which needs a render, so the check is polled for up to 3000 ms until it holds (a settle delay is not an
 *  overflow). Each poll decides and describes in ONE evaluate: it returns "" when the page fits, otherwise the widest
 *  element (tag, id, data attributes, class) with its right edge, clientWidth and scrollWidth, so a timeout reports
 *  the state that failed, not a later one. */
async function expectNoHorizontalOverflow(page: Page, label: string): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const root = document.documentElement;
          if (root.scrollWidth <= root.clientWidth) return "";
          let widest: { el: Element; right: number } | null = null;
          for (const el of Array.from(document.body.querySelectorAll("*"))) {
            const right = el.getBoundingClientRect().right;
            if (widest === null || right > widest.right) widest = { el, right };
          }
          const sizes = `clientWidth ${String(root.clientWidth)}px, scrollWidth ${String(root.scrollWidth)}px`;
          if (widest === null) return `no element found (${sizes})`;
          const data = Array.from(widest.el.attributes)
            .filter((a) => a.name.startsWith("data-") || a.name === "id")
            .map((a) => `${a.name}="${a.value}"`)
            .join(" ");
          const cls = widest.el.getAttribute("class") ?? "";
          return `widest element <${widest.el.tagName.toLowerCase()} ${data}> class="${cls}" right edge ${widest.right.toFixed(2)}px (${sizes})`;
        }),
      { message: `${label}: horizontal overflow`, timeout: 3000 },
    )
    .toBe("");
}

async function noAxeViolations(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
}

test("the Display popover has no axe violations in either theme and in high contrast, and focus returns to its button", async ({ page }) => {
  await stubDisplay(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await openDisplay(page);
  const dialog = page.getByRole("dialog", { name: "Display settings" });
  await expect(dialog.getByTestId("reduced-motion")).toContainText("Reduced motion follows your system setting");

  await noAxeViolations(page); // the system theme (light in the test browser)

  await dialog.getByRole("radio", { name: "Dark" }).check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await noAxeViolations(page);

  await dialog.getByRole("checkbox", { name: "High contrast" }).check();
  await expect(page.locator("html")).toHaveAttribute("data-contrast", "high");
  await noAxeViolations(page);

  await dialog.getByRole("radio", { name: "Light" }).check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await noAxeViolations(page);

  await dialog.getByRole("checkbox", { name: "High contrast" }).uncheck();
  await dialog.getByRole("radio", { name: "Compact" }).check();
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await noAxeViolations(page);

  await closeDisplay(page);
});

test("text size 150 and zoom 130 cause no horizontal overflow, with the popover open or closed", async ({ page }) => {
  await stubDisplay(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await openDisplay(page);
  const dialog = page.getByRole("dialog", { name: "Display settings" });
  await dialog.getByRole("slider", { name: /^Text size/ }).press("End");
  await dialog.getByRole("slider", { name: /^Zoom/ }).press("End");
  await expect(page.locator("html")).toHaveAttribute("data-text-scale", "150");
  await expect(dialog.getByText("130%")).toBeVisible();
  await expectNoHorizontalOverflow(page, "popover open at 1440");
  await noAxeViolations(page);
  await closeDisplay(page);
  await expectNoHorizontalOverflow(page, "popover closed at 1440");

  for (const width of [1100, 700, 390]) {
    await page.setViewportSize({ width, height: 800 });
    await expectNoHorizontalOverflow(page, `width ${String(width)}`);
    await openDisplay(page);
    await expectNoHorizontalOverflow(page, `popover at width ${String(width)}`);
    await closeDisplay(page);
  }
});

test("changes are saved with If-Match semantics, keep privacy_mode, and survive a reload", async ({ page }) => {
  const stub = await stubDisplay(page, { privacy_mode: true, owed_replies_as_tasks: true });
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await openDisplay(page);
  const dialog = page.getByRole("dialog", { name: "Display settings" });
  await dialog.getByRole("radio", { name: "Dark" }).check();
  await dialog.getByRole("slider", { name: /^Zoom/ }).press("End");
  await expect(dialog.getByTestId("display-save-status")).toContainText("Display settings saved.");
  expect(stub.puts).toHaveLength(1);
  expect(stub.puts[0]).toMatchObject({ theme: "dark", zoom: 130, privacy_mode: true, owed_replies_as_tasks: true });

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await openDisplay(page);
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  await expect(page.getByRole("slider", { name: /^Zoom/ })).toHaveValue("130");
});

test("a failed save shows a fixed message and keeps the value", async ({ page }) => {
  await page.route("**/v1/display-settings", async (route) => {
    if (route.request().method() === "PUT") await route.fulfill({ status: 403, json: { detail: "loopback only 10.0.0.5" } });
    else await route.fulfill({ json: { theme: "system", high_contrast: false, density: "comfortable", glow: 1, text_scale: 100, privacy_mode: false, owed_replies_as_tasks: false, zoom: 100, shortcuts: true, revision: 0 } });
  });
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await openDisplay(page);
  const dialog = page.getByRole("dialog", { name: "Display settings" });
  await dialog.getByRole("radio", { name: "Dark" }).check();
  await expect(dialog.getByRole("alert")).toContainText("Could not save display settings. They apply to this session only.");
  await expect(page.getByText("10.0.0.5")).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the shortcuts setting shows the hint only in edit mode while it is on", async ({ page }) => {
  await stubDisplay(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await expect(page.getByTestId("shortcut-hint")).toHaveCount(0);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByTestId("shortcut-hint")).toBeVisible();

  await openDisplay(page);
  await page.getByRole("checkbox", { name: "Keyboard shortcuts" }).uncheck();
  await closeDisplay(page);
  await expect(page.getByTestId("shortcut-hint")).toHaveCount(0);
});

test("a source color choice reaches the page as an attribute and a swatch", async ({ page }) => {
  await stubDisplay(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("widget-events-2")).toBeVisible();
  await openDisplay(page);
  const dialog = page.getByRole("dialog", { name: "Display settings" });
  await dialog.getByRole("combobox", { name: "Gmail" }).selectOption("rose");
  await expect(page.locator("html")).toHaveAttribute("data-src-gmail", "rose");
  await expect(dialog.getByRole("combobox", { name: "Gmail" })).toHaveAccessibleDescription(/passes AA/);
  await noAxeViolations(page);
});
