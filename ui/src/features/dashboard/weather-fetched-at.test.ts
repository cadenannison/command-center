import { describe, expect, it } from "vitest";
import type { ApiEvent } from "./use-events";
import { forecastDays, summaryLine } from "./weather-model";

const NOW = new Date(2026, 10, 12, 15).getTime();
const wx = (id: string, high: number, fetched_at: string): ApiEvent => ({
  id,
  kind: "weather",
  source: "weather",
  title: `High ${String(high)}°, low 30°`,
  start: new Date(2026, 10, 12).toISOString(),
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at,
  has_note: false,
  user_id: "local",
  raw: { high_f: high, low_f: 30 },
});
const good = new Date(2026, 10, 12, 9).toISOString();

describe("forecastDays with an unreadable fetched_at", () => {
  it("never replaces a good entry, whichever comes first", () => {
    expect(forecastDays([wx("a", 58, good), wx("b", 99, "not a date")], NOW)[0]?.high).toBe(58);
    expect(forecastDays([wx("b", 99, "not a date"), wx("a", 58, good)], NOW)[0]?.high).toBe(58);
  });

  it("still shows a day whose only entry is unreadable, as the oldest possible", () => {
    const [day] = forecastDays([wx("b", 99, "nope")], NOW);
    expect(day?.high).toBe(99);
    expect(day?.fetchedAtMs).toBe(0);
  });
});

describe("summaryLine", () => {
  const day = forecastDays([wx("a", 58, good)], NOW)[0];
  it("is one clean line at width tier 1", () => {
    expect(day && summaryLine(day, 1)).toBe("High 58° · Low 30°");
  });
  it("adds the rain chance from width tier 2 when there is one", () => {
    if (!day) throw new Error("no day");
    expect(summaryLine({ ...day, rain: 20 }, 2)).toBe("High 58° · Low 30° · 20% rain");
    expect(summaryLine({ ...day, rain: 20 }, 1)).toBe("High 58° · Low 30°");
    expect(summaryLine({ ...day, rain: null }, 3)).toBe("High 58° · Low 30°");
  });
  it("uses a real minus sign below zero", () => {
    if (!day) throw new Error("no day");
    expect(summaryLine({ ...day, high: -3, low: -12 }, 1)).toBe("High −3° · Low −12°");
  });
});
