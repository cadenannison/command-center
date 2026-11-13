import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/generated/schema";

export type HistoryDay = components["schemas"]["HistoryDay"];
export const HISTORY_STALE_MS = 30_000;

const LISTS = ["done_by_you", "done_by_source", "dismissed", "gone"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEntry(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value["item_id"] === "string" &&
    typeof value["title"] === "string" &&
    typeof value["at"] === "string" &&
    typeof value["group"] === "string" &&
    typeof value["outcome"] === "string"
  );
}

/** True only for the shape the page reads: an array of days, each with a string `day` and, for each list it has, an
 *  array of entries. Anything else is an error, never a crash (decision 0403). */
export function isHistory(value: unknown): value is HistoryDay[] {
  return (
    Array.isArray(value) &&
    value.every(
      (day) =>
        isRecord(day) &&
        typeof day["day"] === "string" &&
        LISTS.every((list) => day[list] === undefined || (Array.isArray(day[list]) && day[list].every(isEntry))),
    )
  );
}

/** GET /v1/history?from&to through the typed client (same origin). Both bounds are local calendar days. */
export async function fetchHistory(from: string, to: string, client: ApiClient = api): Promise<HistoryDay[]> {
  const data: unknown = await unwrap(() => client.GET("/v1/history", { params: { query: { from, to } } }));
  if (!isHistory(data)) throw new ApiError("unknown");
  return data;
}

/** The range is part of the key; a mutation refetches the whole prefix (use-item-actions). */
export function useHistory(from: string, to: string) {
  return useQuery({
    queryKey: ["history", from, to],
    queryFn: () => fetchHistory(from, to),
    staleTime: HISTORY_STALE_MS,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}
