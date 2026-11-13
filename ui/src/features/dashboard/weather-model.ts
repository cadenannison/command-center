import type { Tier } from "../../layout";
import { dayKey, localMidnight } from "./week-model";
import type { ApiEvent } from "./use-events";

/** Pure helpers for the Weather widget. The API gives one `weather` Event per local day with the high and low in
 *  degrees Fahrenheit and the rain chance in `raw`; it has no current temperature, condition or hourly data (decision 0376). */

export interface ForecastDay {
  readonly key: string;
  readonly startMs: number;
  readonly label: string;
  readonly high: number;
  readonly low: number;
  /** Percent, or null when the forecast has none. */
  readonly rain: number | null;
  readonly fetchedAtMs: number;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const TITLE = /High (-?\d+)°, low (-?\d+)°(?:, (\d+)% rain)?/;

/** High, low and rain from `raw`, or from the title ("High 54°, low 38°, 20% rain") if `raw` lacks them. */
export function readTemps(event: ApiEvent): { high: number; low: number; rain: number | null } | null {
  const high = num(event.raw?.["high_f"]);
  const low = num(event.raw?.["low_f"]);
  if (high !== null && low !== null) return { high: Math.round(high), low: Math.round(low), rain: num(event.raw?.["rain_percent"]) };
  const m = TITLE.exec(event.title);
  if (!m) return null;
  return { high: Number(m[1]), low: Number(m[2]), rain: m[3] === undefined ? null : Number(m[3]) };
}

/** Today and the days after it, once each, in date order. Past days and unreadable ones are dropped. */
export function forecastDays(events: readonly ApiEvent[], now: number): ForecastDay[] {
  const today = localMidnight(now);
  const tomorrow = localMidnight(now, 1);
  const byKey = new Map<string, ForecastDay>();
  for (const event of events) {
    if (event.kind !== "weather" || event.start === null || event.start === undefined) continue;
    const startMs = Date.parse(event.start);
    if (Number.isNaN(startMs)) continue;
    const dayStart = localMidnight(startMs);
    if (dayStart < today) continue;
    const temps = readTemps(event);
    if (temps === null) continue;
    const key = dayKey(dayStart);
    const parsed = Date.parse(event.fetched_at);
    // An unreadable fetched_at counts as the oldest possible, so it never replaces a good entry.
    const fetched = Number.isNaN(parsed) ? 0 : parsed;
    const label = dayStart === today ? "Today" : dayStart === tomorrow ? "Tomorrow" : (WEEKDAYS[new Date(dayStart).getDay()] ?? "");
    const existing = byKey.get(key);
    if (existing && existing.fetchedAtMs >= fetched) continue;
    byKey.set(key, { key, startMs: dayStart, label, ...temps, fetchedAtMs: fetched });
  }
  return [...byKey.values()].sort((a, b) => a.startMs - b.startMs);
}

/** A forecast older than this is shown as stale even when the last request worked: the source stopped updating it. */
export const STALE_AFTER_MS = 6 * 3_600_000;

/** The newest `fetched_at` among the days, or null when there are none. */
export const newestFetch = (days: readonly ForecastDay[]): number | null =>
  days.length === 0 ? null : Math.max(...days.map((d) => d.fetchedAtMs));

export const isOutdated = (days: readonly ForecastDay[], now: number): boolean => {
  const newest = newestFetch(days);
  return newest !== null && now - newest > STALE_AFTER_MS;
};

/** The window the widget asks for: from the start of yesterday (so a place ahead of this clock still has its today)
 *  to seven local days after today. */
export function weatherWindow(now: number): { from: string; to: string } {
  return { from: new Date(localMidnight(now, -1)).toISOString(), to: new Date(localMidnight(now, 8)).toISOString() };
}

/** "58°" for a temperature; a real minus sign for below zero. */
export const degrees = (n: number): string => (n < 0 ? `−${String(-n)}°` : `${String(n)}°`);

/** Rows of the outlook after today: width tier 2 shows tomorrow only (when the height has room); width tier 3 shows the
 *  multi-day outlook, 2 days at height tier 1, 4 at tier 2, all at tier 3. Width tier 1 shows none. */
export function outlookDays(days: readonly ForecastDay[], widthTier: Tier, heightTier: Tier): ForecastDay[] {
  const after = days.slice(1);
  if (widthTier === 1) return [];
  if (widthTier === 2) return heightTier >= 2 ? after.slice(0, 1) : [];
  return after.slice(0, heightTier === 1 ? 2 : heightTier === 2 ? 4 : after.length);
}

/** One line under the big number: "High 58° · Low 39°", and at width tier 2 and up " · 20% rain" when the forecast has a chance. */
export function summaryLine(day: ForecastDay, widthTier: Tier): string {
  const parts = [`High ${degrees(day.high)}`, `Low ${degrees(day.low)}`];
  if (widthTier >= 2 && day.rain !== null) parts.push(`${String(day.rain)}% rain`);
  return parts.join(" · ");
}
