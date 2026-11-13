import { formatClock } from "./tasks-model";

/** The state rules the query-backed widgets share, in one pure function (the Tasks widget keeps its own, decision 0373). */
export interface QuerySnapshot {
  readonly hasData: boolean;
  readonly isPending: boolean;
  readonly isError: boolean;
  readonly dataUpdatedAt: number;
  /** Only read when there is data: true when it holds nothing to show. */
  readonly isEmpty: boolean;
}

export type DerivedState =
  | { readonly kind: "loading" }
  | { readonly kind: "error" }
  | { readonly kind: "empty" }
  | { readonly kind: "stale"; readonly lastSynced: string }
  | { readonly kind: "ready" };

/** Loading, error (no data to show), stale (a refresh failed but older data exists), empty or ready. */
export function deriveQueryState(s: QuerySnapshot): DerivedState {
  if (!s.hasData) return s.isPending && !s.isError ? { kind: "loading" } : { kind: "error" };
  if (s.isError) return { kind: "stale", lastSynced: formatClock(new Date(s.dataUpdatedAt)) };
  return s.isEmpty ? { kind: "empty" } : { kind: "ready" };
}
