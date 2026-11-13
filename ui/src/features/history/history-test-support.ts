import type { LedgerEntry } from "./history-model";

export const NOW = new Date(2026, 10, 12, 15, 30).getTime();
export const at = (day: number, hour: number, minute = 0) => new Date(2026, 10, day, hour, minute).toISOString();

export function entry(
  id: string,
  group: LedgerEntry["group"],
  when: string,
  extra: Partial<LedgerEntry> = {},
): LedgerEntry {
  const outcome = group === "dismissed" ? "dismissed" : group === "gone" ? "gone" : "done";
  const completed_by = group === "done_by_you" ? "user" : group === "done_by_source" ? "source" : null;
  return {
    item_id: id,
    source: "canvas",
    kind: "assignment",
    title: `Item ${id}`,
    at: when,
    group,
    reopened: false,
    completed_by,
    outcome,
    ...extra,
  };
}
