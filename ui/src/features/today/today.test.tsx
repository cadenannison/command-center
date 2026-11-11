import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { STALE_AFTER_MS, deriveTodayState, localDateString, type AgendaItem, type QuerySnapshot } from "./state";
import { TodayPage } from "./today-page";
import { TodayView } from "./today-view";

const item = (id: string, title: string): AgendaItem => ({
  id,
  source: "local",
  kind: "task",
  title,
  fetched_at: "2026-11-11T09:00:00Z",
  priority: null,
  has_note: false,
  urgency: 0,
  user_id: "fake-user",
});

const base: QuerySnapshot = { data: undefined, isPending: true, isError: false, errorMessage: null, dataUpdatedAt: 0 };
const NOW = 1_000_000_000;

describe("deriveTodayState", () => {
  it("is loading with no data and no error", () => {
    expect(deriveTodayState(base, NOW)).toEqual({ kind: "loading" });
  });
  it("is error with no data and an error", () => {
    expect(deriveTodayState({ ...base, isError: true, errorMessage: "down" }, NOW)).toEqual({
      kind: "error",
      message: "down",
    });
  });
  it("is empty for an empty fresh list", () => {
    expect(deriveTodayState({ ...base, data: [], isPending: false, dataUpdatedAt: NOW }, NOW)).toEqual({
      kind: "empty",
      stale: null,
    });
  });
  it("is ready and fresh for recent data", () => {
    const s = deriveTodayState({ ...base, data: [item("a", "A")], isPending: false, dataUpdatedAt: NOW - 1000 }, NOW);
    expect(s).toMatchObject({ kind: "ready", stale: null });
  });
  it("is stale when the data is old", () => {
    const at = NOW - STALE_AFTER_MS - 1;
    const s = deriveTodayState({ ...base, data: [item("a", "A")], isPending: false, dataUpdatedAt: at }, NOW);
    expect(s).toMatchObject({ kind: "ready", stale: { since: at, refreshFailed: false } });
  });
  it("is stale, and says the refresh failed, when data exists and a refetch errored", () => {
    const s = deriveTodayState(
      { ...base, data: [item("a", "A")], isPending: false, isError: true, errorMessage: "x", dataUpdatedAt: NOW },
      NOW,
    );
    expect(s).toMatchObject({ kind: "ready", stale: { refreshFailed: true } });
  });
});

describe("localDateString", () => {
  it("formats the local calendar date with zero padding", () => {
    expect(localDateString(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });
});

describe("TodayView", () => {
  it("shows a busy status while loading", () => {
    render(<TodayView state={{ kind: "loading" }} onRetry={vi.fn()} />);
    expect(screen.getByRole("status", { name: "Loading today" })).toHaveAttribute("aria-busy", "true");
  });
  it("shows an alert with a retry button on error", async () => {
    const onRetry = vi.fn();
    render(<TodayView state={{ kind: "error", message: "Could not reach the app." }} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not reach the app.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
  it("shows the empty message", () => {
    render(<TodayView state={{ kind: "empty", stale: null }} onRetry={vi.fn()} />);
    expect(screen.getByText("Nothing scheduled today.")).toBeInTheDocument();
  });
  it("shows rows and a stale notice with a refresh button", () => {
    render(
      <TodayView
        state={{ kind: "ready", items: [item("a", "Write notes")], stale: { since: NOW, refreshFailed: true } }}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText(/Write notes/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Could not refresh.");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("TodayPage through the typed client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });
  const renderPage = () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TodayPage />
      </QueryClientProvider>,
    );
    return client;
  };

  it("loads, then renders the rows from /v1/agenda/day", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(json([item("a", "Read chapter 4")])));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(screen.getByRole("status", { name: "Loading today" })).toBeInTheDocument();
    expect(await screen.findByText(/Read chapter 4/)).toBeInTheDocument();
    const req = (fetchMock.mock.calls[0] as unknown as [Request])[0];
    expect(new URL(req.url, "http://app.test").pathname).toBe("/v1/agenda/day");
  });

  it("renders the empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json([]))));
    renderPage();
    expect(await screen.findByText("Nothing scheduled today.")).toBeInTheDocument();
  });

  it("renders the error state and recovers on retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({}, 503))
      .mockResolvedValue(json([item("a", "Back again")]));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("The app had a problem. Try again.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Back again/)).toBeInTheDocument();
  });

  it("keeps the rows and marks them stale when a refresh fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json([item("a", "Still here")]))
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    const client = renderPage();
    expect(await screen.findByText(/Still here/)).toBeInTheDocument();
    await client.refetchQueries({ queryKey: ["agenda", "day"] });
    expect(await screen.findByText(/Could not refresh\./)).toBeInTheDocument();
    expect(screen.getByText(/Still here/)).toBeInTheDocument();
  });
});
