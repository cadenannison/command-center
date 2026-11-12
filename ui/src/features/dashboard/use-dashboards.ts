import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createDashboard, fetchDashboards } from "./dashboards-api";
import { DEFAULT_LAYOUTS } from "../../layout";
import type { Dashboard } from "./wire";

export const dashboardsKey = ["dashboards"] as const;

export function useDashboards() {
  return useQuery({
    queryKey: dashboardsKey,
    queryFn: () => fetchDashboards(),
  });
}

/** Create the first dashboard, Main, from the default layout (spec, First run). */
export function useCreateMain() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => createDashboard("Main", DEFAULT_LAYOUTS.main),
    onSuccess: (created) => {
      client.setQueryData<Dashboard[]>(dashboardsKey, (old) => [...(old ?? []), created]);
    },
  });
}
