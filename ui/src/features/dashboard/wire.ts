import type { components } from "../../api/generated/schema";
import type { Layout } from "../../layout";

export type Dashboard = components["schemas"]["Dashboard"];
export type DashboardInput = components["schemas"]["DashboardInput"];
type WireLayout = components["schemas"]["Layout"];

/** The layout as /v1 takes it: the same keys the server validates (decision 0355). Built field by field so
 *  nothing outside the model can ride along. */
export function layoutToWire(layout: Layout): WireLayout {
  return {
    version: layout.version,
    items: layout.items.map((i) => ({
      id: i.id,
      widgetId: i.widgetId,
      x: i.x,
      y: i.y,
      w: i.w,
      h: i.h,
      pinned: i.pinned,
      sources: [...i.sources],
      options: Object.fromEntries(
        Object.entries(i.options).filter((e): e is [string, boolean | number] => typeof e[1] !== "string"),
      ),
    })),
  };
}
