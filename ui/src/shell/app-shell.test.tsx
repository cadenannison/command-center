import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_DOCUMENT } from "../features/display/display-api";
import { DisplaySettingsProvider } from "../features/display/display-settings";
import { DisplayProvider } from "../lib/display";
import { ThemeProvider } from "../lib/theme";
import { createAppRouter } from "../router";
import { clearCollapsed, readCollapsed, writeCollapsed } from "./rail-state";

const reply = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

function stub(initial: Record<string, unknown> = {}) {
  const puts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      if (input.method === "PUT") {
        const body = JSON.parse(await input.clone().text()) as Record<string, unknown>;
        puts.push(body);
        return reply({ ...body, revision: 2 });
      }
      if (new URL(input.url).pathname === "/v1/history") return reply([]);
      return reply({ ...DEFAULT_DOCUMENT, ...initial, revision: 1 });
    }),
  );
  return puts;
}

async function mount(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
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
  await screen.findByRole("navigation", { name: "Main" });
  return router;
}

beforeEach(() => {
  clearCollapsed();
  document.documentElement.removeAttribute("data-privacy");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("app shell rail", () => {
  it("lists Today, Chat, History, Focus, then Privacy and Settings, with no Design rules item", async () => {
    stub();
    await mount("/chat");
    const nav = screen.getByRole("navigation", { name: "Main" });
    const names = within(nav)
      .getAllByRole("button")
      .concat(within(nav).getAllByRole("link"))
      .map((el) => ({ el, name: el.textContent }));
    const inOrder = names
      .sort((a, b) => (a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
      .map((n) => n.name);
    expect(inOrder).toEqual(["Menu", "Today", "Chat", "History", "Focus", "Privacy", "Settings"]);
    expect(screen.queryByText(/design rules/i)).not.toBeInTheDocument();
  });

  it("keeps each item's name through hidden text when collapsed, and persists the state", async () => {
    stub();
    const user = userEvent.setup();
    await mount("/chat");
    const toggle = screen.getByRole("button", { name: "Menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(readCollapsed()).toBe(true);
    for (const name of ["Today", "Chat", "History", "Focus", "Settings"]) {
      const link = screen.getByRole("link", { name });
      expect(link).not.toHaveAttribute("aria-label");
      expect(within(link).getByText(name)).toHaveClass("sr-only");
    }
    expect(screen.getByRole("button", { name: "Privacy" })).not.toHaveAttribute("aria-label");
  });

  it("starts collapsed when storage says so, and works when storage throws", async () => {
    stub();
    writeCollapsed(true);
    await mount("/chat");
    expect(screen.getByTestId("rail")).toHaveAttribute("data-collapsed", "true");
    cleanup();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await mount("/chat");
    expect(screen.getByTestId("rail")).toHaveAttribute("data-collapsed", "false");
    await userEvent.setup().click(screen.getByRole("button", { name: "Menu" }));
    expect(screen.getByTestId("rail")).toHaveAttribute("data-collapsed", "true");
  });

  it("marks only the active route with aria-current", async () => {
    stub();
    await mount("/history");
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Chat" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("heading", { name: "History", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("Nothing done or dismissed in the last 30 days.")).toBeInTheDocument();
  });

  it("navigates between placeholder routes", async () => {
    stub();
    const user = userEvent.setup();
    await mount("/chat");
    await user.click(screen.getByRole("link", { name: "Focus" }));
    expect(await screen.findByRole("heading", { name: "Focus", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Focus" })).toHaveAttribute("aria-current", "page");
  });

  it("shows a not-found view with a link to the dashboard for an unknown path", async () => {
    stub();
    await mount("/nope");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/dashboard");
  });

  it("keeps the Display popover reachable from the titlebar", async () => {
    stub();
    await mount("/chat");
    expect(screen.getByRole("banner")).toContainElement(screen.getByRole("button", { name: "Display" }));
  });
});

describe("privacy mask", () => {
  it("toggles data-privacy on the root and saves privacy_mode through the settings", async () => {
    const puts = stub();
    const user = userEvent.setup();
    await mount("/chat");
    const toggle = screen.getByRole("button", { name: "Privacy" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement).toHaveAttribute("data-privacy", "on");
    await waitFor(() => {
      expect(puts.at(-1)).toMatchObject({ privacy_mode: true });
    });
    await user.click(toggle);
    expect(document.documentElement).not.toHaveAttribute("data-privacy");
  });

  it("starts on when the stored setting is on", async () => {
    stub({ privacy_mode: true });
    await mount("/chat");
    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute("data-privacy", "on");
    });
    expect(screen.getByRole("button", { name: "Privacy" })).toHaveAttribute("aria-pressed", "true");
  });

  it("describes itself as a visual mask only", async () => {
    stub();
    await mount("/chat");
    expect(screen.getByRole("button", { name: "Privacy" })).toHaveAccessibleDescription(/visual mask only/i);
  });
});
