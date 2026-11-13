import type { Tier } from "../../layout";
import type { SourceId } from "../../lib/sources";
import { formatClock, safeHref } from "./tasks-model";
import type { ApiEvent } from "./use-events";
import { dayKey, eventSourceId, localMidnight } from "./week-model";

/** Pure grouping for the Events widget. No React and no clock: `now` (epoch ms) is a parameter. Days are local
 *  calendar days built with Date's calendar arithmetic, so a 23 or 25 hour day (DST) is still one day (decision 0378). */

export interface EventRow {
  readonly id: string;
  readonly title: string;
  readonly startMs: number;
  /** Set only when the event really spans time (end after start). */
  readonly endMs: number | null;
  readonly allDay: boolean;
  readonly source: SourceId;
  readonly location: string | null;
  /** An http or https link, or null. */
  readonly href: string | null;
}

export type Marker = "now" | "next" | null;

export interface AgendaRow {
  readonly event: EventRow;
  readonly marker: Marker;
  /** The event began before this day (a multi-day event on a later day). */
  readonly continues: boolean;
}

export interface AgendaDay {
  readonly key: string;
  /** Local days after today: 0 today, 1 tomorrow. */
  readonly offset: number;
  readonly label: string;
  readonly rows: readonly AgendaRow[];
}

export interface Agenda {
  readonly days: readonly AgendaDay[];
  /** Rows listed in `days`, before any height limit. */
  readonly total: number;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;
const parse = (iso: string | null | undefined): number | null => {
  if (iso === null || iso === undefined) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
};

/** The days after today the tall widget lists (today and tomorrow come first), and so the API window. */
export const AGENDA_DAYS = 7;

/** The half-open window [from, to) the widget asks the API for: today and the next six local days. */
export function eventsWindow(now: number): { from: string; to: string } {
  return { from: new Date(localMidnight(now)).toISOString(), to: new Date(localMidnight(now, AGENDA_DAYS)).toISOString() };
}

/** An all-day event starts at a local midnight and ends at a later local midnight (the calendar feeds send dates, not times). */
export function isAllDay(startMs: number, endMs: number | null): boolean {
  return endMs !== null && startMs === localMidnight(startMs) && endMs === localMidnight(endMs) && endMs > startMs;
}

const locationOf = (raw: ApiEvent["raw"]): string | null => {
  const value = raw?.["location"];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
};

/** Calendar events only: weather, tasks, assignments and email never count, nor do cancelled events or ones without a readable start. */
export function eventRowsOf(events: readonly ApiEvent[]): EventRow[] {
  const rows: EventRow[] = [];
  for (const event of events) {
    if (event.kind !== "event" || event.status?.toLowerCase() === "cancelled") continue;
    const startMs = parse(event.start);
    if (startMs === null) continue;
    const end = parse(event.end);
    const endMs = end !== null && end > startMs ? end : null;
    rows.push({
      id: event.id,
      title: event.title,
      startMs,
      endMs,
      allDay: isAllDay(startMs, endMs),
      source: eventSourceId(event.source, "event"),
      location: locationOf(event.raw),
      href: safeHref(event.link ?? null),
    });
  }
  return rows;
}

/** A ranged event belongs to every local day it overlaps (an end exactly at midnight does not reach the next day); a point event to its own day. */
const overlaps = (row: EventRow, dayStart: number, dayEnd: number): boolean =>
  row.endMs === null ? row.startMs >= dayStart && row.startMs < dayEnd : row.startMs < dayEnd && row.endMs > dayStart;

/** Over by `now`: a ranged event after its end, a point event after its start. All-day events last until their end. */
const isPast = (row: EventRow, now: number): boolean => (row.endMs === null ? row.startMs < now : row.endMs <= now);

const inProgress = (row: EventRow, now: number): boolean => !row.allDay && row.endMs !== null && row.startMs <= now && row.endMs > now;

/** "Today", "Tomorrow", then "Mon, Nov 16". */
export function agendaLabel(dayStart: number, now: number): string {
  if (dayStart === localMidnight(now)) return "Today";
  if (dayStart === localMidnight(now, 1)) return "Tomorrow";
  const d = new Date(dayStart);
  return `${WEEKDAYS[d.getDay()] ?? ""}, ${MONTHS[d.getMonth()] ?? ""} ${String(d.getDate())}`;
}

/** Today and the days after it (up to AGENDA_DAYS). Each day lists its all-day events first, then the rest by start time.
 *  Events already over are left out unless `includePast`. Events in progress are marked "now" (every one, on today's row only, not on
 *  later days they continue into) and the earliest timed event still to start is marked "next". A multi-day event counts once per day it is listed on. Empty days are not listed. */
export function buildAgenda(rows: readonly EventRow[], now: number, includePast: boolean): Agenda {
  const sorted = [...rows].sort((a, b) => a.startMs - b.startMs || a.id.localeCompare(b.id));
  const next = sorted.find((row) => !row.allDay && row.startMs > now);
  const days: AgendaDay[] = [];
  let total = 0;
  for (let i = 0; i < AGENDA_DAYS; i += 1) {
    const startMs = localMidnight(now, i);
    const endMs = localMidnight(now, i + 1);
    const inDay = sorted
      .filter((row) => overlaps(row, startMs, endMs) && (includePast || !isPast(row, now)))
      .sort((a, b) => Number(b.allDay) - Number(a.allDay) || a.startMs - b.startMs || a.id.localeCompare(b.id));
    if (inDay.length === 0) continue;
    total += inDay.length;
    days.push({
      key: dayKey(startMs),
      offset: i,
      label: agendaLabel(startMs, now),
      rows: inDay.map((event) => ({
        event,
        marker: i === 0 && inProgress(event, now) ? "now" : event === next && event.startMs >= startMs ? "next" : null,
        continues: event.startMs < startMs,
      })),
    });
  }
  return { days, total };
}

/** Rows shown by height tier: now and next at 1, the rest of today and a little beyond at 2, the long list at 3 (spec, Size rules). */
export const rowLimit = (heightTier: Tier): number => (heightTier === 1 ? 2 : heightTier === 2 ? 6 : 12);

/** Days listed by height tier, counting from today: tier 1 and 2 stop at tomorrow; tier 3 goes on to later days. */
export const dayLimit = (heightTier: Tier): number => (heightTier === 3 ? AGENDA_DAYS : 2);

/** Events already over show only at the tallest tier ("all of today"). */
export const showsPast = (heightTier: Tier): boolean => heightTier === 3;

/** The happening-now marker and next-up emphasis arrive at width tier 3 (the card; spec has the Now chip at every width). */
export const showsMarkers = (widthTier: Tier): boolean => widthTier >= 3;

/** Source dot, end time and location arrive at width tier 2. */
export const showsDetail = (widthTier: Tier): boolean => widthTier >= 2;

/** Keeps the rows the height tier has room for (days left with no rows disappear) and counts the rest. Height tier 1 is
 *  "now and next": rows marked Now or Next come first, then the others in order, so an all-day event cannot push them out. */
export function limitAgenda(agenda: Agenda, heightTier: Tier): { days: AgendaDay[]; more: number } {
  const limit = rowLimit(heightTier);
  const inView = agenda.days.filter((d) => d.offset < dayLimit(heightTier));
  const all = inView.flatMap((d) => d.rows);
  const keep = new Set<AgendaRow>(
    heightTier === 1
      ? [...all.filter((r) => r.marker !== null), ...all.filter((r) => r.marker === null)].slice(0, limit)
      : all.slice(0, limit),
  );
  const days: AgendaDay[] = [];
  for (const day of inView) {
    const rows = day.rows.filter((r) => keep.has(r));
    if (rows.length > 0) days.push({ ...day, rows });
  }
  return { days, more: agenda.total - keep.size };
}

/** The time column: "All day", "Continues" for a timed event begun on an earlier day, else the 12-hour start time. */
export function timeText(row: AgendaRow): string {
  if (row.event.allDay) return "All day";
  return row.continues ? "Continues" : formatClock(new Date(row.event.startMs));
}

/** "until 10:30 AM" for a timed event that has an end; empty otherwise. */
export function untilText(row: AgendaRow): string {
  const { allDay, endMs } = row.event;
  return allDay || endMs === null ? "" : `until ${formatClock(new Date(endMs))}`;
}
