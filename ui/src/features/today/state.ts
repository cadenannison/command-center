import type { components } from "../../api/generated/schema";

export type AgendaItem = components["schemas"]["Event"];

/** Data older than this, or a refresh that failed, makes what is on screen "stale". */
export const STALE_AFTER_MS = 5 * 60 * 1000;

export type TodayState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "empty"; stale: StaleInfo | null }
  | { kind: "ready"; items: readonly AgendaItem[]; stale: StaleInfo | null };

export interface StaleInfo {
  /** When the data on screen was fetched (ms since epoch). */
  since: number;
  /** True when the last refresh failed, not just that time has passed. */
  refreshFailed: boolean;
}

export interface QuerySnapshot {
  data: readonly AgendaItem[] | undefined;
  isPending: boolean;
  isError: boolean;
  errorMessage: string | null;
  dataUpdatedAt: number;
}

/** Four states, one pure function: loading (nothing yet), error (nothing to show), empty, and ready,
 *  where "empty" and "ready" carry a stale flag when the data is old or its refresh failed. */
export function deriveTodayState(q: QuerySnapshot, now: number): TodayState {
  if (q.data === undefined) {
    if (q.isError) return { kind: "error", message: q.errorMessage ?? "Something went wrong." };
    return { kind: "loading" };
  }
  const old = now - q.dataUpdatedAt > STALE_AFTER_MS;
  const stale: StaleInfo | null = q.isError || old ? { since: q.dataUpdatedAt, refreshFailed: q.isError } : null;
  if (q.data.length === 0) return { kind: "empty", stale };
  return { kind: "ready", items: q.data, stale };
}

/** Today's date in the browser's own timezone, as YYYY-MM-DD (decision 0320). */
export function localDateString(now: Date): string {
  const y = String(now.getFullYear()).padStart(4, "0");
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
