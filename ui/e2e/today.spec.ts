import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Needs `pnpm run build` first (the web server is `vite preview`). The agenda call is stubbed.
test("today renders its rows and has no axe violations in either theme", async ({ page }) => {
  await page.route("**/v1/agenda/day*", (route) =>
    route.fulfill({
      json: [
        {
          id: "e1",
          source: "local",
          kind: "task",
          title: "Write the smoke test",
          start: null,
          end: null,
          due: null,
          fetched_at: "2026-11-11T09:00:00Z",
          priority: null,
        },
      ],
    }),
  );

  await page.goto("/today");
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  await expect(page.getByText("Write the smoke test")).toBeVisible();

  const light = await new AxeBuilder({ page }).analyze();
  expect(light.violations).toEqual([]);

  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const dark = await new AxeBuilder({ page }).analyze();
  expect(dark.violations).toEqual([]);
});
