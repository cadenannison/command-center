import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Tier } from "../../layout";
import { EventsWidget } from "./events-widget";
import { json } from "./test-support";
import type { ApiEvent } from "./use-events";

// Thursday, Nov 12, 2026, 3:30 PM Denver. Only Date is faked, so timers and promises still run.
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
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mount(handler: () => Response | Promise<Response>, tiers: { w: Tier; h: Tier } = { w: 3, h: 3 }) {
  const fetchMock = vi.fn(async () => handler());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EventsWidget title="Events" source="cal" status="Calendar" widthTier={tiers.w} heightTier={tiers.h} />
    </QueryClientProvider>,
  );
  return { fetchMock, client };
}

const rowsOf = () => screen.findAllByTestId("event-row");
const day = [
  event("done", at(12, 9), { end: at(12, 10) }),
  event("now", at(12, 15), { end: at(12, 16), raw: { location: "Room 4" }, link: "https://cal.example/e/now" }),
  event("next", at(12, 17), { end: at(12, 18) }),
  event("tm", at(13, 8, 30), { end: at(13, 9) }),
  event("all", new Date(2026, 10, 12).toISOString(), { end: new Date(2026, 10, 13).toISOString() }),
  { ...event("wx", at(12, 0)), kind: "weather" as const },
];

describe("EventsWidget", () => {
  it("shows loading, then Today and Tomorrow groups with all-day first and 12-hour times", async () => {
    mount(() => json(day), { w: 3, h: 3 });
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    const rows = await rowsOf();
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Today", "Tomorrow"]);
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringMatching(/^All dayMeeting all/),
      expect.stringMatching(/^9:00 AMMeeting done/),
      expect.stringMatching(/^3:00 PMMeeting now/),
      expect.stringMatching(/^5:00 PMMeeting next/),
      expect.stringMatching(/^8:30 AMMeeting tm/),
    ]);
    expect(screen.getByText("4 today")).toBeInTheDocument();
  });

  it("asks GET /v1/events for today and six more local days, same origin, read only", async () => {
    const { fetchMock } = mount(() => json(day));
    await rowsOf();
    const [[request]] = fetchMock.mock.calls as unknown as [[Request]];
    const url = new URL(request.url);
    expect(request.method).toBe("GET");
    expect(url.origin).toBe(window.location.origin);
    expect(url.pathname).toBe("/v1/events");
    expect(url.searchParams.get("from")).toBe(new Date(2026, 10, 12).toISOString());
    expect(url.searchParams.get("to")).toBe(new Date(2026, 10, 19).toISOString());
  });

  it("W1 shows time and title only", async () => {
    mount(() => json(day), { w: 1, h: 3 });
    const rows = await rowsOf();
    const now = rows.find((r) => r.textContent.includes("Meeting now")) as HTMLElement;
    expect(now.textContent).toBe("3:00 PMMeeting now");
    expect(now.querySelector("[data-source]")).toBeNull();
    expect(now).not.toHaveAttribute("data-marker");
  });

  it("W2 adds the source dot, end time and location, but no Now or Next", async () => {
    mount(() => json(day), { w: 2, h: 3 });
    const rows = await rowsOf();
    const now = rows.find((r) => r.textContent.includes("Meeting now")) as HTMLElement;
    expect(now).toHaveTextContent("until 4:00 PM · Room 4");
    expect(now.querySelector("[data-source]")).toHaveAttribute("data-source", "cal");
    expect(within(now).getByRole("img", { name: "Calendar" })).toBeInTheDocument();
    expect(screen.queryByText("Now")).not.toBeInTheDocument();
    expect(screen.queryByText("Next")).not.toBeInTheDocument();
  });

  it("W3 marks the event in progress Now and the following one Next", async () => {
    mount(() => json(day), { w: 3, h: 3 });
    const rows = await rowsOf();
    expect(rows.map((r) => r.getAttribute("data-marker"))).toEqual([null, null, "now", "next", null]);
    expect(within(rows[2] as HTMLElement).getByText("Now")).toBeInTheDocument();
    expect(within(rows[3] as HTMLElement).getByText("Next")).toBeInTheDocument();
  });

  it("H1 shows two upcoming rows and +N more; H2 hides what is over; H3 shows all of today", async () => {
    mount(() => json(day), { w: 3, h: 1 });
    expect((await rowsOf()).map((r) => r.textContent)).toHaveLength(2);
    expect(screen.getByTestId("events-more")).toHaveTextContent("+2 more");
    cleanup();
    mount(() => json(day), { w: 3, h: 2 });
    const h2 = await rowsOf();
    expect(h2).toHaveLength(4);
    expect(screen.queryByText("Meeting done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("events-more")).not.toBeInTheDocument();
  });

  it("H3 goes on to later days; H2 does not and counts them as more", async () => {
    const later = [...day, event("mon", at(16, 9), { end: at(16, 10) })];
    mount(() => json(later), { w: 3, h: 3 });
    await rowsOf();
    expect(screen.getByRole("heading", { level: 3, name: "Mon, Nov 16" })).toBeInTheDocument();
    cleanup();
    mount(() => json(later), { w: 3, h: 2 });
    await rowsOf();
    expect(screen.queryByRole("heading", { level: 3, name: "Mon, Nov 16" })).not.toBeInTheDocument();
    expect(screen.getByTestId("events-more")).toHaveTextContent("+1 more");
  });

  it("links out only for http(s), in a new tab with rel noopener noreferrer, named for the event", async () => {
    mount(
      () =>
        json([
          event("a", at(12, 16), { link: "https://cal.example/e/a" }),
          event("b", at(12, 17), { link: "javascript:alert(1)" }),
          event("c", at(12, 18)),
        ]),
    );
    await rowsOf();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAccessibleName("Open Meeting a in a new tab");
    expect(links[0]).toHaveAttribute("href", "https://cal.example/e/a");
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows the empty state when nothing is on the calendar, ignoring weather", async () => {
    mount(() => json([{ ...event("wx", at(12, 0)), kind: "weather" }]));
    expect(await screen.findByText("Nothing on your calendar.")).toBeInTheDocument();
    expect(screen.queryAllByTestId("event-row")).toHaveLength(0);
  });

  it("shows a fixed-text error with Retry, never the server's text", async () => {
    let fail = true;
    const { fetchMock } = mount(() => (fail ? json({ detail: "secret server text" }, 500) : json(day)));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load your events. Try again.");
    expect(alert).not.toHaveTextContent("secret server text");
    fail = false;
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await rowsOf()).toHaveLength(5);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeps the rows and says so when a refresh fails (stale)", async () => {
    let fail = false;
    const { client } = mount(() => (fail ? json({}, 500) : json(day)));
    await rowsOf();
    fail = true;
    await client.refetchQueries({ queryKey: ["events"] });
    expect(await screen.findByText(/Showing older data/)).toBeInTheDocument();
    expect(screen.getAllByTestId("event-row")).toHaveLength(5);
  });
});
