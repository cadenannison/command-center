import { SOURCES, type SourceId } from "../../lib/sources";
import type { Tier } from "../../layout";
import type { ApiEvent } from "./use-events";

/** Pure grouping for the Week widget. No React and no clock: `now` (epoch ms) and the first weekday are parameters.
 *  Days are local calendar days built with Date's calendar arithmetic, so a 23 or 25 hour day (DST) is still one day. */

export interface WeekItem {
  readonly id: string;
  readonly title: string;
  readonly startMs: number;
  /** Set only when the item really spans time (end after start). */
  readonly endMs: number | null;
  readonly source: SourceId;
}

export interface WeekDay {
  readonly key: string;
  readonly startMs: number;
  readonly endMs: number;
  readonly weekday: string;
  readonly dayOfMonth: number;
  readonly isToday: boolean;
  readonly items: readonly WeekItem[];
  readonly sources: readonly SourceId[];
}

export interface NextEvent {
  readonly item: WeekItem;
  readonly ongoing: boolean;
}

export interface Week {
  readonly days: readonly WeekDay[];
  readonly next: NextEvent | null;
  readonly total: number;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const parse = (iso: string | null | undefined): number | null => {
  if (iso === null || iso === undefined) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
};

/** Convert Intl's week info (1 Monday … 7 Sunday) to Date.getDay() numbering (0 Sunday … 6 Saturday). */
export const firstDayFromIntl = (firstDay: number | undefined): number =>
  firstDay === undefined || !Number.isInteger(firstDay) || firstDay < 1 || firstDay > 7 ? 0 : firstDay % 7;

interface LocaleWithWeek {
  getWeekInfo?: () => { firstDay: number };
  weekInfo?: { firstDay: number };
}

/** The user's local first weekday (0 Sunday … 6 Saturday); Sunday, the design's convention, when the browser cannot say. */
export function localFirstDay(language: string = globalThis.navigator.language): number {
  try {
    const locale = new Intl.Locale(language) as unknown as LocaleWithWeek;
    return firstDayFromIntl((locale.getWeekInfo?.() ?? locale.weekInfo)?.firstDay);
  } catch {
    return 0;
  }
}

/** Local midnight of `now`'s date, moved by `days` calendar days (never by 24 hours). */
export const localMidnight = (now: number, days = 0): number => {
  const d = new Date(now);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days).getTime();
};

/** Local midnight of the first day of the week containing `now`. */
export function weekStart(now: number, firstDay: number): number {
  const back = (new Date(now).getDay() - firstDay + 7) % 7;
  return localMidnight(now, -back);
}

/** The half-open window [from, to) the widget asks the API for: seven local days from the week's first day. */
export function weekWindow(now: number, firstDay: number): { from: string; to: string } {
  const start = weekStart(now, firstDay);
  return { from: new Date(start).toISOString(), to: new Date(localMidnight(start, 7)).toISOString() };
}

const pad = (n: number): string => String(n).padStart(2, "0");
export const dayKey = (ms: number): string => {
  const d = new Date(ms);
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

/** The design source for an item: a known source id as is, any other calendar feed is Calendar, other kinds My tasks. */
export function eventSourceId(source: string, kind: ApiEvent["kind"]): SourceId {
  const known = SOURCES.find((entry) => entry.id === source);
  if (known) return known.id;
  return kind === "event" ? "cal" : "manual";
}

/** Items the widget counts: calendar events when Calendar is selected, and other open items (by due time) from the
 *  other selected sources. Weather and done items never count; an item without a readable time is left out. */
export function weekItemsOf(events: readonly ApiEvent[], sources: readonly SourceId[]): WeekItem[] {
  const items: WeekItem[] = [];
  for (const event of events) {
    if (event.kind === "weather" || event.status === "done") continue;
    const source = eventSourceId(event.source, event.kind);
    if (!sources.includes(event.kind === "event" ? "cal" : source)) continue;
    const startMs = event.kind === "event" ? parse(event.start) : (parse(event.due) ?? parse(event.start));
    if (startMs === null) continue;
    const end = event.kind === "event" ? parse(event.end) : null;
    items.push({ id: event.id, title: event.title, startMs, endMs: end !== null && end > startMs ? end : null, source });
  }
  return items.sort((a, b) => a.startMs - b.startMs || a.id.localeCompare(b.id));
}

/** A ranged item belongs to every local day it overlaps (an end exactly at midnight does not reach the next day);
 *  a point item belongs to the day it falls in. */
const overlaps = (item: WeekItem, dayStart: number, dayEnd: number): boolean =>
  item.endMs === null
    ? item.startMs >= dayStart && item.startMs < dayEnd
    : item.startMs < dayEnd && item.endMs > dayStart;

/** Seven local days from the week's first day, each with its items in time order, and the next event after `now`. */
export function buildWeek(unsorted: readonly WeekItem[], now: number, firstDay: number): Week {
  const items = [...unsorted].sort((a, b) => a.startMs - b.startMs || a.id.localeCompare(b.id));
  const first = weekStart(now, firstDay);
  const days: WeekDay[] = [];
  for (let i = 0; i < 7; i += 1) {
    const startMs = localMidnight(first, i);
    const endMs = localMidnight(first, i + 1);
    const inDay = items.filter((item) => overlaps(item, startMs, endMs));
    const sources = SOURCES.map((s) => s.id).filter((id) => inDay.some((item) => item.source === id));
    const date = new Date(startMs);
    days.push({
      key: dayKey(startMs),
      startMs,
      endMs,
      weekday: WEEKDAYS[date.getDay()] ?? "",
      dayOfMonth: date.getDate(),
      isToday: now >= startMs && now < endMs,
      items: inDay,
      sources,
    });
  }
  const weekEnd = localMidnight(first, 7);
  const upcoming = items.filter(
    (item) => item.startMs < weekEnd && (item.endMs === null ? item.startMs >= now : item.endMs > now),
  );
  const nextItem = upcoming[0];
  return {
    days,
    next: nextItem ? { item: nextItem, ongoing: nextItem.startMs <= now } : null,
    total: days.reduce((n, day) => n + day.items.length, 0),
  };
}

/** How many items to list under each day: none at height tier 1 and 2, up to 3 at tier 3 (spec, Size rules). */
export const itemsPerDay = (heightTier: Tier): number => (heightTier === 3 ? 3 : 0);

/** Whether the next-event line shows: from height tier 2 up. */
export const showsNext = (heightTier: Tier): boolean => heightTier >= 2;

/** "Mon, Nov 9": the day's full name for a screen reader, built from the same local date. */
export function dayLabel(day: WeekDay): string {
  const d = new Date(day.startMs);
  const long = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][d.getDay()] ?? "";
  const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  return `${long}, ${months[d.getMonth()] ?? ""} ${String(d.getDate())}`;
}

/** "1 event", "3 events", "No events". */
export const countText = (n: number): string => (n === 0 ? "No events" : n === 1 ? "1 event" : `${String(n)} events`);
