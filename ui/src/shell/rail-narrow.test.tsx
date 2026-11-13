import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_DOCUMENT } from "../features/display/display-api";
import { DisplaySettingsProvider } from "../features/display/display-settings";
import { DisplayProvider } from "../lib/display";
import { ThemeProvider } from "../lib/theme";
import { createAppRouter } from "../router";
import { clearCollapsed, readCollapsed } from "./rail-state";

// jsdom has no layout or media queries, so these read the classes that drive the narrow rule (decision 0397).
// Whether the rail really is icon width at 390px, and the page does not overflow, is for the browser spec.

async function mount() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ ...DEFAULT_DOCUMENT, revision: 1 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    ),
  );
  const router = createAppRouter(createMemoryHistory({ initialEntries: ["/chat"] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <ThemeProvider>
      <DisplayProvider>
        <QueryClientProvider client={client}>
          <DisplaySettingsProvider>
            <RouterProvider router={router} />
          </DisplaySettingsProvider>
        </QueryClientProvider>
      </DisplayProvider>
    </ThemeProvider>,
  );
  return screen.findByRole("navigation", { name: "Main" });
}

beforeEach(() => {
  clearCollapsed();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("rail below the md breakpoint", () => {
  it("is icon width and hides its text from sight but not from the name, by class", async () => {
    const nav = await mount();
    expect(nav).toHaveClass("w-44", "max-md:w-14");
    for (const name of ["Today", "Chat", "History", "Focus", "Settings"]) {
      const link = within(nav).getByRole("link", { name });
      expect(link).not.toHaveAttribute("aria-label");
      expect(within(link).getByText(name)).toHaveClass("max-md:sr-only");
    }
    expect(within(nav).getByRole("button", { name: "Privacy" })).not.toHaveAttribute("aria-label");
  });

  it("hides the collapse toggle below md and does not touch the stored preference", async () => {
    const nav = await mount();
    expect(within(nav).getByRole("button", { name: "Menu" })).toHaveClass("max-md:hidden");
    expect(readCollapsed()).toBe(false);
    expect(nav).toHaveAttribute("data-collapsed", "false");
  });
});
