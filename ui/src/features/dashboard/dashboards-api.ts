import { api, unwrap, type ApiClient } from "../../api/client";
import type { Layout } from "../../layout";
import { layoutToWire, type Dashboard } from "./wire";

export function fetchDashboards(client: ApiClient = api): Promise<Dashboard[]> {
  return unwrap(() => client.GET("/v1/dashboards"));
}

export function createDashboard(name: string, layout: Layout, client: ApiClient = api): Promise<Dashboard> {
  return unwrap(() =>
    client.POST("/v1/dashboards", {
      body: { name, layout: layoutToWire(layout) },
    }),
  );
}

/** Replace a dashboard if the stored revision is `revision` (If-Match). A stale revision is an ApiError with status 409. */
export function replaceDashboard(
  id: string,
  revision: number,
  name: string,
  layout: Layout,
  client: ApiClient = api,
): Promise<Dashboard> {
  return unwrap(() =>
    client.PUT("/v1/dashboards/{dashboard_id}", {
      params: {
        path: { dashboard_id: id },
        header: { "if-match": `"${String(revision)}"` },
      },
      body: { name, layout: layoutToWire(layout) },
    }),
  );
}
