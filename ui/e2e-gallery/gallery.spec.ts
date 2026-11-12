import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Runs against the dev server (playwright.gallery.config.ts), because /gallery is dev only (decision 0342).
// Fonts are served from ui/public/fonts, so the page loads the real Sora file.

async function open(page: Page) {
  await page.goto("/gallery");
  await expect(page.getByRole("heading", { name: "Gallery" })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
}

function controls(page: Page) {
  return page.getByRole("group", { name: "Display controls" });
}

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
}

test("gallery has no axe violations in dark, light and high contrast", async ({ page }) => {
  await open(page);

  await controls(page).getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await axe(page);

  await controls(page).getByRole("button", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await axe(page);

  await controls(page).getByLabel("High contrast").check();
  await expect(page.locator("html")).toHaveAttribute("data-contrast", "high");
  await axe(page);

  await controls(page).getByRole("button", { name: "Dark" }).click();
  await axe(page);
});

test("Sora with tnum gives 1111 and 0000 the same width", async ({ page }) => {
  await open(page);
  const loaded = await page.evaluate(async () => {
    await document.fonts.load('18px "Sora"');
    return document.fonts.check('18px "Sora"');
  });
  expect(loaded, "Sora did not load, so the width check would measure the fallback font").toBe(true);

  const widths = await page.evaluate(() => {
    const width = (id: string) => document.getElementById(id)?.getBoundingClientRect().width ?? Number.NaN;
    return { ones: width("tnum-ones"), zeros: width("tnum-zeros") };
  });
  expect(widths.ones).toBeGreaterThan(0);
  expect(Math.abs(widths.ones - widths.zeros)).toBeLessThan(0.01);
  const feature = await page.locator("#tnum-ones").evaluate((el) => getComputedStyle(el).fontFeatureSettings);
  expect(feature).toContain("tnum");
});
