import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import type { NeedsMeItem } from "./needs-me-model";

export const NEEDS_ME_STALE_MS = 30_000;

/** GET /v1/needs-me through the typed client: the only request the Needs me widget makes (same origin, read-only). */
export function fetchNeedsMe(client: ApiClient = api): Promise<NeedsMeItem[]> {
  return unwrap(() => client.GET("/v1/needs-me"));
}

export function useNeedsMe() {
  return useQuery({
    queryKey: ["needs-me"],
    queryFn: () => fetchNeedsMe(),
    staleTime: NEEDS_ME_STALE_MS,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}
