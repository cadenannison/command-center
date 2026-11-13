import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SourceId } from "../../lib/sources";
import type { Tier } from "../../layout";
import { json } from "./test-support";
import type { ApiEvent } from "./use-events";
import { WeekWidget } from "./week-widget";

// Thursday, Nov 12, 2026, 3:30 PM local. Only Date is faked, so timers and promises still run.
const NOW = new Date(2026, 10, 12, 15, 30).getTime();
const at = (d: number, h: number, min = 0) => new Date(2026, 10, d, h, min).toISOString();

const event = (id: string, start: string, extra: Partial<ApiEvent> = {}): ApiEvent => ({
  id,
  kind: "event",
  source: "apple_calendar",
  title: `Meeting ${id}`,
  start,
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: "2026-11-12T10:00:00Z",
  has_note: false,
  user_id: "local",
  ...extra,
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  vi.spyOn(globalThis.navigator, "language", "get").mockReturnValue("en-US");
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mount(
  handler: () => Response | Promise<Response>,
  tiers: { w: Tier; h: Tier } = { w: 3, h: 3 },
  sources: readonly SourceId[] = ["cal"],
) {
  const fetchMock = vi.fn(async () => handler());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WeekWidget title="This week" source="cal" status="Calendar" widthTier={tiers.w} heightTier={tiers.h} sources={sources} />
    </QueryClientProvider>,
  );
  return { fetchMock, client };
}

const week = [event("a", at(10, 9)), event("b", at(12, 17)), event("c", at(12, 18)), event("d", at(13, 8))];

describe("WeekWidget", () => {
  it("shows loading, then the seven days with counts and today highlighted", async () => {
    mount(() => json(week));
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    const days = await screen.findAllByTestId("week-day");
    expect(days).toHaveLength(7);
    expect(days.map((d) => d.getAttribute("aria-label"))).toEqual([
      "Sunday, November 8: No events",
      "Monday, November 9: No events",
      "Tuesday, November 10: 1 event",
      "Wednesday, November 11: No events",
      "Thursday, November 12, today: 2 events",
      "Friday, November 13: 1 event",
      "Saturday, November 14: No events",
    ]);
    expect(days.filter((d) => d.dataset["today"] === "true")).toHaveLength(1);
    expect(days[4]).toHaveAttribute("aria-current", "date");
    expect(screen.getByText("4 this week")).toBeInTheDocument();
  });

  it("asks GET /v1/events for the local week from Sunday, same origin, read only", async () => {
    const { fetchMock } = mount(() => json(week));
    await screen.findAllByTestId("week-day");
    const [[request]] = fetchMock.mock.calls as unknown as [[Request]];
    const url = new URL(request.url);
    expect(request.method).toBe("GET");
    expect(url.origin).toBe(window.location.origin);
    expect(url.pathname).toBe("/v1/events");
    expect(url.searchParams.get("from")).toBe(new Date(2026, 10, 8).toISOString());
    expect(url.searchParams.get("to")).toBe(new Date(2026, 10, 15).toISOString());
  });

  it("names the next event from height tier 2, and hides it at tier 1", async () => {
    mount(() => json(week), { w: 3, h: 2 });
    expect(await screen.findByTestId("week-next")).toHaveTextContent("Next: Meeting b, Today 5:00 PM");
  });

  it("hides the next line at height tier 1", async () => {
    mount(() => json(week), { w: 3, h: 1 });
    await screen.findAllByTestId("week-day");
    expect(screen.queryByTestId("week-next")).not.toBeInTheDocument();
  });

  it("says Now when an event is under way", async () => {
    mount(() => json([event("x", at(12, 15), { end: at(12, 16) })]), { w: 3, h: 2 });
    expect(await screen.findByTestId("week-next")).toHaveTextContent("Now: Meeting x");
  });

  it("lists each day's first three events with 12-hour times at height tier 3", async () => {
    const many = [9, 10, 11, 12].map((h) => event(`m${String(h)}`, at(13, h)));
    mount(() => json(many), { w: 3, h: 3 });
    const items = await screen.findAllByTestId("week-item");
    expect(items.map((i) => i.textContent)).toEqual(["9:00 AMMeeting m9", "10:00 AMMeeting m10", "11:00 AMMeeting m11"]);
    expect(screen.getByText("+1 more")).toBeInTheDocument();
  });

  it("shows source dots from width tier 2 only", async () => {
    const dots = (day: HTMLElement) => day.querySelectorAll("[data-source]");
    mount(() => json(week), { w: 1, h: 1 });
    const narrow = await screen.findAllByTestId("week-day");
    expect(dots(narrow[4] as HTMLElement)).toHaveLength(0);
    cleanup();
    mount(() => json(week), { w: 2, h: 1 });
    const standard = await screen.findAllByTestId("week-day");
    expect(dots(standard[4] as HTMLElement)).toHaveLength(1);
    expect(dots(standard[4] as HTMLElement)[0]).toHaveAttribute("data-source", "cal");
    expect(dots(standard[3] as HTMLElement)).toHaveLength(0);
  });

  it("shows the empty state when the week has nothing", async () => {
    mount(() => json([]));
    expect(await screen.findByText("Nothing scheduled this week.")).toBeInTheDocument();
    expect(screen.queryAllByTestId("week-day")).toHaveLength(0);
  });

  it("shows a fixed-text error with Retry, never the server's text", async () => {
    let fail = true;
    const { fetchMock } = mount(() => (fail ? json({ detail: "secret server text" }, 500) : json(week)));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load your week. Try again.");
    expect(alert).not.toHaveTextContent("secret server text");
    fail = false;
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findAllByTestId("week-day")).toHaveLength(7);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeps the strip and says so when a refresh fails (stale)", async () => {
    let fail = false;
    const { client } = mount(() => (fail ? json({}, 500) : json(week)));
    await screen.findAllByTestId("week-day");
    fail = true;
    await client.refetchQueries({ queryKey: ["events"] });
    expect(await screen.findByText(/Showing older data/)).toBeInTheDocument();
    expect(screen.getAllByTestId("week-day")).toHaveLength(7);
  });

  it("counts assignments only when their source is selected", async () => {
    const hw = event("hw", at(11, 9), { kind: "assignment", source: "canvas", due: at(11, 23) });
    mount(() => json([week[0] as ApiEvent, hw]), { w: 3, h: 3 }, ["cal", "canvas"]);
    const days = await screen.findAllByTestId("week-day");
    expect(days[3]).toHaveAttribute("aria-label", "Wednesday, November 11: 1 event");
  });
});
