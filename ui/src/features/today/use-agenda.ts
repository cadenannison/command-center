import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import type { AgendaItem } from "./state";

/** GET /v1/agenda/day?date= : the items of one local day, through the typed client. */
export function fetchDayAgenda(date: string, client: ApiClient = api): Promise<AgendaItem[]> {
  return unwrap(() =>
    client.GET("/v1/agenda/{period}", { params: { path: { period: "day" }, query: { date } } }),
  );
}

export function useDayAgenda(date: string) {
  return useQuery({
    queryKey: ["agenda", "day", date],
    queryFn: () => fetchDayAgenda(date),
    refetchInterval: 60_000,
  });
}
