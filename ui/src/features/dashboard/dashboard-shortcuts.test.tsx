import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_DOCUMENT } from "../display/display-api";
import { DisplaySettingsProvider } from "../display/display-settings";
import { DisplayProvider } from "../../lib/display";
import { ThemeProvider } from "../../lib/theme";
import { DashboardPage } from "./dashboard-page";
import { dashboardOf, installGridEnv, json } from "./test-support";

// Undo and redo shortcuts on the dashboard follow the shortcuts setting and edit mode (card E2, decision 0392).
function stubApi(shortcuts: boolean): string[] {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: Request) => {
      const path = new URL(input.url).pathname;
      seen.push(path);
      if (path === "/v1/display-settings") return Promise.resolve(json({ ...DEFAULT_DOCUMENT, shortcuts, revision: 1 }));
      if (path === "/v1/summary") return Promise.resolve(json({ summary: { headline: "Quiet.", priorities: [], heads_up: [] }, provider: "gemini", cached: true }));
      if (path === "/v1/needs-me") return Promise.resolve(json([]));
      return Promise.resolve(json([dashboardOf("main", "Main")]));
    }),
  );
  return seen;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <DisplayProvider>
          <DisplaySettingsProvider>
            <DashboardPage />
          </DisplaySettingsProvider>
        </DisplayProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const widgetX = (id: string) => screen.getByTestId(`widget-${id}`).getAttribute("data-x");

async function editAndMove() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Edit" }));
  const header = screen.getByRole("button", { name: /^Move Events, W\d/ });
  fireEvent.keyDown(header, { key: "Enter" });
  fireEvent.keyDown(header, { key: "ArrowLeft" });
  fireEvent.keyDown(header, { key: "Enter" });
  return header;
}

beforeEach(() => {
  installGridEnv(1200, 1400);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("dashboard shortcuts", () => {
  it("undoes and redoes a move with Ctrl+Z and Ctrl+Shift+Z in edit mode, and shows the hint", async () => {
    stubApi(true);
    renderPage();
    const before = (await screen.findByTestId("widget-events-2")).getAttribute("data-x");
    await waitFor(() => {
      expect(screen.queryByTestId("shortcut-hint")).toBeNull();
    });
    const header = await editAndMove();
    await waitFor(() => {
      expect(screen.getByTestId("shortcut-hint")).toBeInTheDocument();
    });
    const moved = widgetX("events-2");
    expect(moved).not.toBe(before);
    fireEvent.keyDown(header, { key: "z", ctrlKey: true });
    expect(widgetX("events-2")).toBe(before);
    expect(screen.getByTestId("live-region")).toHaveTextContent("Undone.");
    fireEvent.keyDown(header, { key: "z", ctrlKey: true, shiftKey: true });
    expect(widgetX("events-2")).toBe(moved);
    expect(screen.getByTestId("live-region")).toHaveTextContent("Redone.");
  });

  it("does nothing and shows no hint when the shortcuts setting is off", async () => {
    const seen = stubApi(false);
    renderPage();
    await screen.findByTestId("widget-events-2");
    await waitFor(() => {
      expect(seen).toContain("/v1/display-settings");
    });
    const header = await editAndMove();
    const moved = widgetX("events-2");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByTestId("shortcut-hint")).toBeNull();
    fireEvent.keyDown(header, { key: "z", ctrlKey: true });
    expect(widgetX("events-2")).toBe(moved);
  });

  it("holds undo and redo while a widget is picked up, and works again once it is dropped", async () => {
    stubApi(true);
    renderPage();
    await screen.findByTestId("widget-events-2");
    const header = await editAndMove();
    const moved = widgetX("events-2");
    // Pick it up again: there is a move to undo, but not mid pick-up.
    fireEvent.keyDown(header, { key: "Enter" });
    fireEvent.keyDown(header, { key: "ArrowLeft" });
    const held = widgetX("events-2");
    const undo = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true, cancelable: true });
    header.dispatchEvent(undo);
    expect(undo.defaultPrevented).toBe(false);
    expect(widgetX("events-2")).toBe(held);
    expect(screen.getByTestId("live-region")).not.toHaveTextContent("Undone.");
    const redo = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true });
    header.dispatchEvent(redo);
    expect(redo.defaultPrevented).toBe(false);
    // Drop it; the shortcut is live again and undoes that last move.
    fireEvent.keyDown(header, { key: "Enter" });
    await waitFor(() => {
      expect(screen.getByTestId("live-region")).not.toHaveTextContent("Undone.");
    });
    expect(widgetX("events-2")).toBe(held);
    expect(held).not.toBe(moved);
    fireEvent.keyDown(header, { key: "z", ctrlKey: true });
    expect(widgetX("events-2")).toBe(moved);
    expect(screen.getByTestId("live-region")).toHaveTextContent("Undone.");
  });

  it("does nothing outside edit mode", async () => {
    stubApi(true);
    renderPage();
    await screen.findByTestId("widget-events-2");
    const event = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true, cancelable: true });
    document.body.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(screen.queryByTestId("shortcut-hint")).toBeNull();
  });
});
