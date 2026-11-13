import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type ApiClient } from "../../api/client";
import type { TaskItem } from "./tasks-model";

export const TASKS_STALE_MS = 30_000;

/** GET /v1/tasks through the typed client: the only request the Tasks widget makes (same origin, read-only). */
export function fetchTasks(client: ApiClient = api): Promise<TaskItem[]> {
  return unwrap(() => client.GET("/v1/tasks"));
}

export function useTasks() {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: () => fetchTasks(),
    staleTime: TASKS_STALE_MS,
    refetchOnWindowFocus: true,
  });
}
