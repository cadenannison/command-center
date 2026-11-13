import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import type { components } from "../../api/generated/schema";

export type ApiEvent = components["schemas"]["Event"];
export const EVENTS_STALE_MS = 30_000;

/** GET /v1/events?from&to through the typed client (same origin, read-only). Both bounds are ISO instants. */
export function fetchEvents(from: string, to: string, client: ApiClient = api): Promise<ApiEvent[]> {
  return unwrap(() => client.GET("/v1/events", { params: { query: { from, to } } }));
}

/** The window is part of the key, so the Week and Weather widgets cache separately and a new day refetches. */
export function useEvents(from: string, to: string, name: "week" | "weather") {
  return useQuery({
    queryKey: ["events", name, from, to],
    queryFn: () => fetchEvents(from, to),
    staleTime: EVENTS_STALE_MS,
    refetchOnWindowFocus: true,
  });
}
