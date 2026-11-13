import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./dashboard-page";
import { dashboardOf, installGridEnv, json } from "./test-support";

// The Summary card is pinned above the grid, it is not a grid widget (decisions 0331, 0350, 0381).
const SUMMARY = { summary: { headline: "A quiet day.", priorities: ["Read chapter 4"], heads_up: [] }, provider: "gemini", cached: true };

function stub(summary: () => Response) {
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: Request) => {
      const path = new URL(input.url).pathname;
      paths.push(path);
      if (path === "/v1/summary") return Promise.resolve(summary());
      if (path === "/v1/dashboards") return Promise.resolve(json([dashboardOf("main", "Main")]));
      return Promise.resolve(json([]));
    }),
  );
  return paths;
}

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DashboardPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  installGridEnv(1200, 1400);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the Summary card on the dashboard", () => {
  it("comes before the grid in the DOM and is not inside it", async () => {
    stub(() => json(SUMMARY));
    renderPage();
    const card = await screen.findByTestId("summary-card");
    const grid = screen.getByTestId("dashboard-grid");
    expect(card.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(grid.contains(card)).toBe(false);
    expect(grid.querySelector('[data-testid^="widget-summary"]')).toBeNull();
  });

  it("stays visible and focusable in edit mode, and asks for the summary only once", async () => {
    const paths = stub(() => json(SUMMARY));
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByTestId("summary-card")).toBeVisible();
    const button = await screen.findByRole("button", { name: "Collapse summary" });
    await user.click(button);
    expect(button).toHaveFocus();
    expect(screen.getByRole("button", { name: "Expand summary" })).toBeInTheDocument();
    expect(paths.filter((p) => p === "/v1/summary")).toHaveLength(1);
  });

  it("shows the off state on a 404 while the grid still renders", async () => {
    stub(() => json({ detail: "Summaries are off" }, 404));
    renderPage();
    expect(await screen.findByText("Summaries are off")).toBeInTheDocument();
    expect(screen.getByTestId("widget-events-2")).toBeInTheDocument();
  });

  it("a failing summary does not blank the dashboard", async () => {
    stub(() => json({ detail: "boom" }, 500));
    renderPage();
    expect(await screen.findByText("Could not load the summary. Try again.")).toBeInTheDocument();
    expect(screen.getByTestId("widget-events-2")).toBeInTheDocument();
  });
});
