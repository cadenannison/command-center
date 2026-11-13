import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import type { components } from "../../api/generated/schema";

export type ApiEvent = components["schemas"]["Event"];
export const EVENTS_STALE_MS = 30_000;

/** GET /v1/events?from&to through the typed client (same origin, read-only). Both bounds are ISO instants. */
export function fetchEvents(from: string, to: string, client: ApiClient = api): Promise<ApiEvent[]> {
  return unwrap(() => client.GET("/v1/events", { params: { query: { from, to } } }));
}

/** The window is part of the key, so the Week, Weather and Events widgets cache separately and a new day refetches.
 *  keepPreviousData keeps the last window on screen while the next one loads (a date change at midnight). */
export function useEvents(from: string, to: string, name: "week" | "weather" | "events") {
  return useQuery({
    queryKey: ["events", name, from, to],
    queryFn: () => fetchEvents(from, to),
    staleTime: EVENTS_STALE_MS,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}
