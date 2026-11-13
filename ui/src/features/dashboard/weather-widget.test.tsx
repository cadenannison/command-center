import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Tier } from "../../layout";
import { json } from "./test-support";
import type { ApiEvent } from "./use-events";
import { WeatherWidget } from "./weather-widget";

const NOW = new Date(2026, 10, 12, 15, 30).getTime();
const FRESH = new Date(2026, 10, 12, 14, 0).toISOString();

const wx = (day: number, high: number, low: number, rain: number | null, fetched = FRESH): ApiEvent => ({
  id: `wx-${String(day)}`,
  kind: "weather",
  source: "weather",
  title: `High ${String(high)}°, low ${String(low)}°`,
  start: new Date(2026, 10, day).toISOString(),
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: fetched,
  has_note: false,
  user_id: "local",
  raw: { high_f: high, low_f: low, rain_percent: rain },
});

const forecast = (fetched = FRESH) => [
  wx(12, 58, 39, 20, fetched),
  wx(13, 52, 36, 0, fetched),
  wx(14, 47, 33, 60, fetched),
  wx(15, 45, 30, 10, fetched),
  wx(16, 44, 29, null, fetched),
];

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
      <WeatherWidget title="Weather" source="wx" status="Weather" widthTier={tiers.w} heightTier={tiers.h} />
    </QueryClientProvider>,
  );
  return { fetchMock, client };
}

describe("WeatherWidget tiers", () => {
  it("W1 shows today's high and low and no outlook", async () => {
    mount(() => json(forecast()), { w: 1, h: 3 });
    expect(await screen.findByTestId("weather-high")).toHaveTextContent("58°");
    expect(screen.getByText("High today. Low 39°")).toBeInTheDocument();
    expect(screen.queryByTestId("weather-day")).not.toBeInTheDocument();
  });

  it("W2 adds the rain chance and tomorrow", async () => {
    mount(() => json(forecast()), { w: 2, h: 2 });
    expect(await screen.findByText("High today. Low 39°. 20% chance of rain.")).toBeInTheDocument();
    const rows = screen.getAllByTestId("weather-day");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Tomorrow");
    expect(rows[0]).toHaveTextContent("52° / 36°");
  });

  it("W3 adds the multi-day outlook, limited by height", async () => {
    mount(() => json(forecast()), { w: 3, h: 1 });
    const rows = await screen.findAllByTestId("weather-day");
    expect(rows.map((r) => r.textContent)).toEqual(["Tomorrow0% rain52° / 36°", "Sat60% rain47° / 33°"]);
  });

  it("W3 at height tier 3 lists every later day and leaves out a missing rain chance", async () => {
    mount(() => json(forecast()), { w: 3, h: 3 });
    const rows = await screen.findAllByTestId("weather-day");
    expect(rows).toHaveLength(4);
    expect(rows[3]).toHaveTextContent("Mon44° / 29°");
    expect(rows[3]).not.toHaveTextContent("rain");
  });
});

describe("WeatherWidget states", () => {
  it("shows loading first", () => {
    mount(() => new Promise<Response>(() => {}));
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });

  it("is not connected when the API holds no forecast", async () => {
    mount(() => json([]));
    expect(await screen.findByText("Weather isn't connected yet.")).toBeInTheDocument();
  });

  it("shows a fixed-text error with Retry, never the server's text", async () => {
    let fail = true;
    const { fetchMock } = mount(() => (fail ? json({ detail: "secret server text" }, 500) : json(forecast())));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the forecast. Try again.");
    expect(alert).not.toHaveTextContent("secret server text");
    fail = false;
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("weather-high")).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeps the forecast and says so when a refresh fails (stale)", async () => {
    let fail = false;
    const { client } = mount(() => (fail ? json({}, 500) : json(forecast())));
    await screen.findByTestId("weather-high");
    fail = true;
    await client.refetchQueries({ queryKey: ["events"] });
    expect(await screen.findByText(/Showing older data/)).toBeInTheDocument();
    expect(screen.getByTestId("weather-high")).toBeInTheDocument();
  });

  it("is stale, with the fetch time, when the source stopped updating the forecast", async () => {
    mount(() => json(forecast(new Date(2026, 10, 12, 6, 5).toISOString())));
    expect(await screen.findByText("Showing older data. Last synced 6:05 AM.")).toBeInTheDocument();
    expect(screen.getByTestId("weather-high")).toBeInTheDocument();
  });

  it("is read-only: only same-origin GET /v1/events", async () => {
    const { fetchMock } = mount(() => json(forecast()));
    await screen.findByTestId("weather-high");
    for (const [request] of fetchMock.mock.calls as unknown as [Request][]) {
      expect(request.method).toBe("GET");
      expect(new URL(request.url).pathname).toBe("/v1/events");
      expect(new URL(request.url).origin).toBe(window.location.origin);
    }
  });
});
