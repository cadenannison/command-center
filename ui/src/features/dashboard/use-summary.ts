import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import type { ApiSummary } from "./summary-model";

/** GET /v1/summary can call the AI provider (SummaryService.get builds and stores the day's summary on the first
 *  request), so it is fetched once per day per mount: no focus refetch, no polling, no reconnect refetch, no retry,
 *  and a long staleTime (decision 0381). The Retry button is the only way to ask again. */
export const SUMMARY_STALE_MS = 5 * 60_000;

export function fetchSummary(date: string, client: ApiClient = api): Promise<ApiSummary> {
  return unwrap(() => client.GET("/v1/summary", { params: { query: { date } } }));
}

export function useSummary(date: string) {
  return useQuery({
    queryKey: ["summary", date],
    queryFn: () => fetchSummary(date),
    staleTime: SUMMARY_STALE_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: false,
    retry: false,
    placeholderData: keepPreviousData,
  });
}
