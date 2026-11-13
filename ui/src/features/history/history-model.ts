import type { HistoryDay, } from "./use-history";
import { summaryDay } from "../dashboard/summary-model";

export type LedgerEntry = NonNullable<HistoryDay["done_by_you"]>[number];
export type HistoryFilter = "all" | "done" | "dismissed";

/** How many local days the page asks for, today included (decision 0403). */
export const HISTORY_DAYS = 30;

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

/** The request range: the last HISTORY_DAYS local days up to and including today. The clock is a parameter. */
export function historyRange(nowMs: number): { from: string; to: string } {
  const start = new Date(nowMs);
  start.setDate(start.getDate() - (HISTORY_DAYS - 1));
  return { from: summaryDay(start.getTime()), to: summaryDay(nowMs) };
}

/** "Thursday, Nov 12" from a YYYY-MM-DD key, read as a local date so no zone shifts it. */
export function dayHeading(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
  return `${WEEKDAYS[date.getDay()] ?? ""}, ${MONTHS[date.getMonth()] ?? ""} ${String(date.getDate())}`;
}

export const OUTCOME_LABEL: Record<LedgerEntry["outcome"], string> = {
  done: "Done",
  dismissed: "Dismissed",
  gone: "Gone",
};

export interface HistoryRow {
  readonly key: string;
  readonly entry: LedgerEntry;
  /** Restore is offered only for today's entries you made: your own check-off or a dismissal (decision 0403). */
  readonly restorable: boolean;
}

export interface DayView {
  readonly day: string;
  readonly heading: string;
  /** The whole day's counts, whatever the filter and search show. */
  readonly done: number;
  readonly dismissed: number;
  readonly rows: readonly HistoryRow[];
}

export function matches(entry: LedgerEntry, filter: HistoryFilter, query: string): boolean {
  if (filter !== "all" && entry.outcome !== filter) return false;
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return entry.title.toLowerCase().includes(q) || (entry.note ?? "").toLowerCase().includes(q);
}

/** Days newest first, entries newest first inside a day, cut by the filter and the search. A day with nothing left is dropped. */
export function buildDays(days: readonly HistoryDay[], filter: HistoryFilter, query: string, today: string): DayView[] {
  const views: DayView[] = [];
  for (const d of [...days].sort((a, b) => b.day.localeCompare(a.day))) {
    const all = [...(d.done_by_you ?? []), ...(d.done_by_source ?? []), ...(d.dismissed ?? []), ...(d.gone ?? [])];
    const seen = new Map<string, number>();
    const rows = all
      .filter((entry) => matches(entry, filter, query))
      .sort((a, b) => b.at.localeCompare(a.at))
      .map<HistoryRow>((entry) => {
        // Stable across a refetch: no list index, so a row keeps its key when another one leaves.
        const base = `${d.day}-${entry.group}-${entry.item_id}-${entry.at}`;
        const n = seen.get(base) ?? 0;
        seen.set(base, n + 1);
        return {
        key: n === 0 ? base : `${base}-${String(n)}`,
        entry,
        restorable: d.day === today && (entry.group === "done_by_you" || entry.group === "dismissed"),
        };
      });
    if (rows.length === 0) continue;
    views.push({
      day: d.day,
      heading: dayHeading(d.day),
      done: (d.done_by_you ?? []).length + (d.done_by_source ?? []).length,
      dismissed: (d.dismissed ?? []).length,
      rows,
    });
  }
  return views;
}
