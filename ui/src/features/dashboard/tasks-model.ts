import type { components } from "../../api/generated/schema";
import { SOURCES, type SourceId } from "../../lib/sources";
import type { Tier } from "../../layout";

/** Pure grouping and formatting for the Tasks widget. No React, no clock: `now` is always a parameter. */

export type TaskItem = components["schemas"]["TaskItem"];
export type TaskReason = components["schemas"]["UrgencyReason"];

export type GroupId = "overdue" | "next48" | "later" | "undated";

export interface TaskGroup {
  readonly id: GroupId;
  readonly label: string;
  readonly items: readonly TaskItem[];
}

const HOUR_MS = 3_600_000;
export const NEXT_WINDOW_MS = 48 * HOUR_MS;

const LABELS: Record<GroupId, string> = {
  overdue: "Overdue",
  next48: "Due in the next 48 hours",
  later: "Later",
  undated: "No due date",
};
const ORDER: readonly GroupId[] = ["overdue", "next48", "later", "undated"];

const dueMs = (item: TaskItem): number | null => {
  if (item.due === null) return null;
  const ms = Date.parse(item.due);
  return Number.isNaN(ms) ? null : ms;
};

/** Which group a due time belongs to. Due exactly 48 hours from now is still "next 48 hours"; one
 *  millisecond later is "Later". Due exactly now is not yet overdue. An unreadable date counts as undated. */
export function groupOf(due: number | null, now: number): GroupId {
  if (due === null) return "undated";
  if (due < now) return "overdue";
  return due - now <= NEXT_WINDOW_MS ? "next48" : "later";
}

/** Open items only, in the server's order inside each group. Empty groups are left out; "No due date" is always last. */
export function groupTasks(items: readonly TaskItem[], now: number): TaskGroup[] {
  const buckets = new Map<GroupId, TaskItem[]>(ORDER.map((id) => [id, []]));
  for (const item of items) {
    if (item.done) continue;
    buckets.get(groupOf(dueMs(item), now))?.push(item);
  }
  return ORDER.flatMap((id) => {
    const list = buckets.get(id) ?? [];
    return list.length > 0 ? [{ id, label: LABELS[id], items: list }] : [];
  });
}

export const openCount = (groups: readonly TaskGroup[]): number => groups.reduce((n, g) => n + g.items.length, 0);

/** Height tier 1 shows the top 3 rows, tier 2 up to 6, tier 3 all of them (spec, Size rules). */
export function rowLimit(heightTier: Tier): number {
  return heightTier === 1 ? 3 : heightTier === 2 ? 6 : Number.POSITIVE_INFINITY;
}

/** Keep the first `limit` rows across the groups. `more` is how many were cut. */
export function limitRows(groups: readonly TaskGroup[], limit: number): { groups: TaskGroup[]; more: number } {
  let left = limit;
  const kept: TaskGroup[] = [];
  for (const group of groups) {
    if (left <= 0) break;
    const items = group.items.slice(0, left);
    left -= items.length;
    kept.push({ ...group, items });
  }
  return { groups: kept, more: Math.max(0, openCount(groups) - openCount(kept)) };
}

/** "3:05 PM", "12:00 AM": 12-hour, local time, minutes always printed. */
export function formatClock(date: Date): string {
  const hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${String(hours % 12 === 0 ? 12 : hours % 12)}:${minutes} ${hours < 12 ? "AM" : "PM"}`;
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

const startOfDay = (date: Date): number => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** "Today 3:05 PM", "Tomorrow 9:00 AM", "Fri 4:00 PM" within the next week, "Nov 20, 4:00 PM" beyond it,
 *  "Yesterday 6:00 PM" and "Nov 3, 6:00 PM" before. Empty for no or unreadable due. */
export function formatDue(due: string | null, now: number): string {
  if (due === null) return "";
  const ms = Date.parse(due);
  if (Number.isNaN(ms)) return "";
  const date = new Date(ms);
  const clock = formatClock(date);
  const days = Math.round((startOfDay(date) - startOfDay(new Date(now))) / (24 * HOUR_MS));
  if (days === 0) return `Today ${clock}`;
  if (days === 1) return `Tomorrow ${clock}`;
  if (days === -1) return `Yesterday ${clock}`;
  if (days > 1 && days < 7) return `${DAYS[date.getDay()] ?? ""} ${clock}`;
  return `${MONTHS[date.getMonth()] ?? ""} ${String(date.getDate())}, ${clock}`;
}

/** The reason that added the most points (the first of equals); null when there are none. */
export function topReason(reasons: readonly TaskReason[]): TaskReason | null {
  let best: TaskReason | null = null;
  for (const reason of reasons) if (best === null || reason.points > best.points) best = reason;
  return best;
}

/** "+3" for a gain, "0" for none, a real minus sign for a loss. */
export function formatPoints(points: number): string {
  return points > 0 ? `+${String(points)}` : points < 0 ? `−${String(-points)}` : "0";
}

/** The link to render, or null. Only http and https are links: javascript:, data:, file: and relative strings are not. */
export function safeHref(link: string | null): string | null {
  if (link === null) return null;
  try {
    const url = new URL(link);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

/** The design's source for a server source string; anything unknown (such as "local") is a My tasks item. */
export function sourceIdOf(source: string): SourceId {
  return SOURCES.find((entry) => entry.id === source)?.id ?? "manual";
}

export interface TasksSnapshot {
  readonly data: readonly TaskItem[] | undefined;
  readonly isPending: boolean;
  readonly isError: boolean;
  readonly dataUpdatedAt: number;
}

export type TasksState =
  | { readonly kind: "loading" }
  | { readonly kind: "error" }
  | { readonly kind: "empty" }
  | { readonly kind: "stale"; readonly lastSynced: string }
  | { readonly kind: "ready" };

/** Loading, error (no data to show), empty (no open item), stale (a refresh failed but older data exists) or ready. */
export function deriveTasksState(snapshot: TasksSnapshot): TasksState {
  if (snapshot.data === undefined) {
    return snapshot.isPending && !snapshot.isError ? { kind: "loading" } : { kind: "error" };
  }
  if (snapshot.isError) {
    const at = new Date(snapshot.dataUpdatedAt);
    return { kind: "stale", lastSynced: formatClock(at) };
  }
  return snapshot.data.some((item) => !item.done) ? { kind: "ready" } : { kind: "empty" };
}
