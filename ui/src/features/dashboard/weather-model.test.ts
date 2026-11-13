import { describe, expect, it } from "vitest";
import type { ApiEvent } from "./use-events";
import { degrees, forecastDays, isOutdated, newestFetch, outlookDays, readTemps, STALE_AFTER_MS, weatherWindow } from "./weather-model";

process.env["TZ"] = "America/Denver";

const at = (y: number, m: number, d: number, h = 0, min = 0) => new Date(y, m - 1, d, h, min).getTime();

const wx = (day: number, extra: Partial<ApiEvent> = {}, raw: Record<string, unknown> | null = { high_f: 54.4, low_f: 38.2, rain_percent: 20 }): ApiEvent => ({
  id: `wx-${String(day)}`,
  kind: "weather",
  source: "weather",
  title: "High 54°, low 38°, 20% rain",
  start: new Date(2026, 10, day).toISOString(),
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: new Date(at(2026, 11, 12, 9)).toISOString(),
  has_note: false,
  user_id: "local",
  ...(raw ? { raw } : {}),
  ...extra,
});

const now = at(2026, 11, 12, 15);

describe("readTemps", () => {
  it("reads rounded temperatures and rain from raw", () => {
    expect(readTemps(wx(12))).toEqual({ high: 54, low: 38, rain: 20 });
  });

  it("falls back to the title when raw is missing", () => {
    expect(readTemps(wx(12, {}, null))).toEqual({ high: 54, low: 38, rain: 20 });
    expect(readTemps(wx(12, { title: "High -3°, low -12°" }, null))).toEqual({ high: -3, low: -12, rain: null });
  });

  it("is null when neither can be read", () => {
    expect(readTemps(wx(12, { title: "Sunny" }, null))).toBeNull();
    expect(readTemps(wx(12, { title: "Sunny" }, { high_f: "hot", low_f: 3 }))).toBeNull();
  });

  it("keeps a missing rain chance as null", () => {
    expect(readTemps(wx(12, {}, { high_f: 50, low_f: 40 }))?.rain).toBeNull();
  });
});

describe("forecastDays", () => {
  it("labels today, tomorrow and then the weekday, in date order", () => {
    const days = forecastDays([wx(15), wx(12), wx(14), wx(13)], now);
    expect(days.map((d) => d.label)).toEqual(["Today", "Tomorrow", "Sat", "Sun"]);
  });

  it("drops past days, non-weather events and unreadable ones", () => {
    const days = forecastDays(
      [wx(11), wx(12), wx(13, { kind: "event" }), wx(14, { start: null }), wx(15, { start: "junk" }), wx(16, { title: "x" }, null)],
      now,
    );
    expect(days.map((d) => d.label)).toEqual(["Today"]);
  });

  it("keeps the newest of two forecasts for one day", () => {
    const older = wx(12, { id: "old", fetched_at: new Date(at(2026, 11, 12, 6)).toISOString() }, { high_f: 40, low_f: 30 });
    const newer = wx(12, { id: "new", fetched_at: new Date(at(2026, 11, 12, 9)).toISOString() }, { high_f: 60, low_f: 45 });
    expect(forecastDays([newer, older], now)[0]?.high).toBe(60);
    expect(forecastDays([older, newer], now)[0]?.high).toBe(60);
  });

  it("is empty when there is no forecast", () => {
    expect(forecastDays([], now)).toEqual([]);
  });
});

describe("freshness", () => {
  it("is outdated only past six hours since the newest fetch", () => {
    const days = forecastDays([wx(12)], now);
    const fetched = newestFetch(days) ?? 0;
    expect(isOutdated(days, fetched + STALE_AFTER_MS)).toBe(false);
    expect(isOutdated(days, fetched + STALE_AFTER_MS + 1)).toBe(true);
    expect(isOutdated([], now)).toBe(false);
    expect(newestFetch([])).toBeNull();
  });
});

describe("outlookDays", () => {
  const days = forecastDays([12, 13, 14, 15, 16, 17, 18].map((d) => wx(d)), now);

  it("shows nothing after today at width tier 1", () => {
    for (const h of [1, 2, 3] as const) expect(outlookDays(days, 1, h)).toEqual([]);
  });

  it("shows tomorrow only at width tier 2, and only from height tier 2", () => {
    expect(outlookDays(days, 2, 1)).toEqual([]);
    expect(outlookDays(days, 2, 2).map((d) => d.label)).toEqual(["Tomorrow"]);
    expect(outlookDays(days, 2, 3).map((d) => d.label)).toEqual(["Tomorrow"]);
  });

  it("shows the multi-day outlook at width tier 3: 2, 4 or all days by height", () => {
    expect(outlookDays(days, 3, 1)).toHaveLength(2);
    expect(outlookDays(days, 3, 2)).toHaveLength(4);
    expect(outlookDays(days, 3, 3)).toHaveLength(6);
  });

  it("copes with a short forecast", () => {
    expect(outlookDays(days.slice(0, 1), 3, 3)).toEqual([]);
  });
});

describe("formatting and window", () => {
  it("prints a real minus sign below zero", () => {
    expect(degrees(58)).toBe("58°");
    expect(degrees(0)).toBe("0°");
    expect(degrees(-4)).toBe("−4°");
  });

  it("asks from the start of yesterday to eight local days ahead", () => {
    expect(weatherWindow(now)).toEqual({
      from: new Date(at(2026, 11, 11)).toISOString(),
      to: new Date(at(2026, 11, 20)).toISOString(),
    });
  });
});
