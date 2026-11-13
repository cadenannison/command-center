import { expect, type Page } from "@playwright/test";

/** The stored display settings the specs start from (revision 0 is what the server returns when nothing is saved). */
export const DISPLAY_DEFAULTS = {
  theme: "system",
  high_contrast: false,
  density: "comfortable",
  glow: 1,
  text_scale: 100,
  privacy_mode: false,
  owed_replies_as_tasks: false,
  zoom: 100,
  shortcuts: true,
};

export interface DisplayStub {
  /** The body of every PUT, parsed, in order. */
  readonly puts: Record<string, unknown>[];
}

/** Answer GET and PUT /v1/display-settings from memory, with a revision that counts up, like the server. */
export async function stubDisplay(page: Page, initial: Record<string, unknown> = {}): Promise<DisplayStub> {
  let stored: Record<string, unknown> = { ...DISPLAY_DEFAULTS, ...initial };
  let revision = 0;
  const puts: Record<string, unknown>[] = [];
  await page.route("**/v1/display-settings", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      puts.push(body);
      stored = body;
      revision += 1;
    }
    await route.fulfill({ json: { ...stored, revision, updated_at: "2026-11-12T10:00:00Z" } });
  });
  return { puts };
}

/** Open the Display settings popover. */
export async function openDisplay(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Display", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Display settings" })).toBeVisible();
}

/** Close it with Escape; focus goes back to the Display button. */
export async function closeDisplay(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Display settings" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Display", exact: true })).toBeFocused();
}

/** Force the dark theme through the Display settings popover (it replaced the header's Dark button, card E2).
 *  Call it AFTER page.goto: it opens the popover. Stub display settings before the page loads, with
 *  stubDisplay in the spec's setup, so no GET to /v1/display-settings goes unstubbed. */
export async function chooseDark(page: Page): Promise<void> {
  await openDisplay(page);
  await page.getByRole("radio", { name: "Dark" }).check();
  await closeDisplay(page);
}
