import type { components } from "../../api/generated/schema";
import type { Tier } from "../../layout";
import type { SourceId } from "../../lib/sources";
import { formatClock } from "./tasks-model";
import { eventSourceId, localMidnight } from "./week-model";

/** Pure helpers for the Needs me widget (decision 0387). No React and no clock: `now` (epoch ms) is always a parameter.
 *  The server filters, ranks and caps the list (0385, 0386); nothing here reorders it. */

export type NeedsMeItem = components["schemas"]["NeedsMeItem"];
export type NeedsMeReason = components["schemas"]["UrgencyReason"];

export type KindLabel = "Task" | "Assignment" | "Reply" | "Event";

/** The label for a row's kind. Weather is never listed (the server does not send it), so it has none. */
export function kindLabel(kind: NeedsMeItem["kind"]): KindLabel | null {
  switch (kind) {
    case "task":
      return "Task";
    case "assignment":
      return "Assignment";
    case "email":
      return "Reply";
    case "event":
      return "Event";
    default:
      return null;
  }
}

/** The rows to show: the server's order, with anything that has no kind label (weather) left out. */
export function needsMeRows(items: readonly NeedsMeItem[]): NeedsMeItem[] {
  return items.filter((item) => kindLabel(item.kind) !== null);
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

/** "" for the same local day as `now`, then "Tomorrow", a weekday within the next week, else "Nov 20". Days are local
 *  calendar days built with Date's calendar arithmetic, so a 23 or 25 hour day (DST) is still one day. */
export function dayPrefix(ms: number, now: number): string {
  const start = localMidnight(ms);
  if (start === localMidnight(now)) return "";
  if (start === localMidnight(now, 1)) return "Tomorrow";
  if (start > localMidnight(now, 1) && start < localMidnight(now, 7)) return WEEKDAYS[new Date(ms).getDay()] ?? "";
  const d = new Date(ms);
  return `${MONTHS[d.getMonth()] ?? ""} ${String(d.getDate())}`;
}

const stamp = (ms: number, now: number): string => [dayPrefix(ms, now), formatClock(new Date(ms))].filter((p) => p !== "").join(" ");

/** The time column of a row, from its one time `at` (due, else start):
 *  an event that has started is "Now" (the server lists an event only while it is in progress or still ahead, 0385);
 *  an event ahead is "Starts 2:30 PM" ("Starts Tomorrow 9:00 AM" on another day);
 *  anything else is "Overdue" once its time has passed, else "Due 5:00 PM". Due exactly now is not yet overdue.
 *  No or unreadable `at` gives "". */
export function whenLabel(item: Pick<NeedsMeItem, "kind" | "at">, now: number): string {
  if (item.at === null) return "";
  const ms = Date.parse(item.at);
  if (Number.isNaN(ms)) return "";
  if (item.kind === "event") return ms <= now ? "Now" : `Starts ${stamp(ms, now)}`;
  return ms < now ? "Overdue" : `Due ${stamp(ms, now)}`;
}

/** True when the row is an overdue task, assignment or reply (it gets the danger color). */
export function isOverdue(item: Pick<NeedsMeItem, "kind" | "at">, now: number): boolean {
  return whenLabel(item, now) === "Overdue";
}

/** Height tier 1 shows the top 3 rows, tier 2 up to 6, tier 3 all of them (spec, Size rules). */
export function rowLimit(heightTier: Tier): number {
  return heightTier === 1 ? 3 : heightTier === 2 ? 6 : Number.POSITIVE_INFINITY;
}

/** The first `limit` rows and how many were cut. */
export function limitRows<T>(rows: readonly T[], limit: number): { shown: T[]; more: number } {
  const shown = rows.slice(0, limit);
  return { shown, more: rows.length - shown.length };
}

/** "1 needs you", "4 need you". */
export function countText(count: number): string {
  return `${String(count)} ${count === 1 ? "needs" : "need"} you`;
}

/** The design's source for a row; a calendar event is always Calendar, anything unknown is My tasks. */
export function rowSource(item: Pick<NeedsMeItem, "source" | "kind">): SourceId {
  return eventSourceId(item.source, item.kind === "event" ? "event" : "task");
}
