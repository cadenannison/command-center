import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./dashboard-page";
import { dashboardOf, installGridEnv, json } from "./test-support";

interface Put {
  readonly ifMatch: string | null;
  readonly items: readonly { id: string; w: number; h: number }[];
}

/** Every change the edit tools make must reach the server through the same PUT with If-Match (decision 0362). */
function stubApi() {
  const puts: Put[] = [];
  let revision = 1;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const path = new URL(input.url).pathname;
      if (input.method === "PUT") {
        const body = (await input.clone().json()) as { layout: { items: Put["items"] } };
        puts.push({ ifMatch: input.headers.get("if-match"), items: body.layout.items });
        revision += 1;
        return json(dashboardOf("main", "Main", revision));
      }
      if (path === "/v1/dashboards") return json([dashboardOf("main", "Main", revision)]);
      if (path === "/v1/summary") {
        return json({ summary: { headline: "Quiet.", priorities: [], heads_up: [] }, provider: "gemini", cached: true });
      }
      return json([]);
    }),
  );
  return puts;
}

beforeEach(() => {
  installGridEnv(1200, 1400);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DashboardPage />
    </QueryClientProvider>,
  );
}

describe("edit tools save through the existing path", () => {
  it("saves an add and then an undo, each with If-Match and the latest layout only", async () => {
    const puts = stubApi();
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));

    // Add: one PUT on Done carrying the new widget, against revision 1.
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    await user.click(await screen.findByRole("button", { name: "Add Weather" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(puts).toHaveLength(1);
    });
    expect(puts[0]?.ifMatch).toBe('"1"');
    expect(puts[0]?.items.map((i) => i.id)).toEqual(["needs_me-1", "events-2", "weather-1"]);

    // Undo, then redo: the saved layout follows the history, and the revision moves on.
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(puts).toHaveLength(2);
    });
    expect(puts[1]?.ifMatch).toBe('"2"');
    expect(puts[1]?.items.map((i) => i.id)).toEqual(["needs_me-1", "events-2"]);
  });

  it("saves a size preset and then a template reset, each with its own If-Match", async () => {
    const puts = stubApi();
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Options for Events" }));
    await user.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: /^S ·/ }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(puts).toHaveLength(1);
    });
    expect(puts[0]?.ifMatch).toBe('"1"');
    expect(puts[0]?.items.find((i) => i.id === "events-2")).toMatchObject({ w: 3, h: 5 });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Reset" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("radio", { name: /Work/ }));
    await user.click(screen.getByRole("button", { name: "Apply template" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(puts).toHaveLength(2);
    });
    expect(puts[1]?.ifMatch).toBe('"2"');
    expect(puts[1]?.items.map((i) => i.id)).toEqual(["events-1", "owed_replies-2", "my_tasks-3", "weather-4"]);
  });
});
