import { autoArrange } from "./grid";
import { clampSize, getWidget } from "./registry";
import type { SourceId } from "../lib/sources";
import { LAYOUT_VERSION, type Layout, type LayoutItem, type WidgetId } from "./types";

export type TemplateName = "main" | "student" | "work" | "minimal";

/** [widget, w, h] and optional sources, in reading order (from the prototype's starting layouts). */
type Entry = readonly [WidgetId, number, number] | readonly [WidgetId, number, number, readonly SourceId[]];

export const TEMPLATE_ENTRIES: Readonly<Record<TemplateName, readonly Entry[]>> = {
  main: [
    ["needs_me", 4, 10],
    ["tasks", 5, 10],
    ["events", 3, 10],
    ["week", 5, 6],
    ["owed_replies", 4, 6],
    ["weather", 3, 6],
  ],
  student: [
    ["needs_me", 4, 10],
    ["canvas", 4, 10],
    ["learningsuite", 4, 10],
    ["week", 7, 6, ["canvas", "ls"]],
    ["events", 5, 6],
  ],
  work: [
    ["events", 5, 10],
    ["owed_replies", 4, 10],
    ["my_tasks", 3, 10],
    ["weather", 3, 6],
  ],
  minimal: [
    ["needs_me", 7, 10],
    ["events", 5, 10],
  ],
};

export function buildTemplate(name: TemplateName): Layout {
  const items: LayoutItem[] = TEMPLATE_ENTRIES[name].map((entry, n) => {
    const [widgetId, w, h] = entry;
    const def = getWidget(widgetId);
    if (!def) throw new Error(`unknown widget ${widgetId}`);
    const size = clampSize({ w, h }, def);
    return {
      id: `${widgetId}-${String(n + 1)}`,
      widgetId,
      x: 0,
      y: n, // one row per entry, so reading order is entry order
      ...size,
      pinned: false,
      sources: entry[3] ?? def.defaultSources,
      options: {},
    };
  });
  return autoArrange({ version: LAYOUT_VERSION, items }, 12);
}

/** Main is applied at first run (spec, First run). */
export const DEFAULT_LAYOUTS: Readonly<Record<TemplateName, Layout>> = {
  main: buildTemplate("main"),
  student: buildTemplate("student"),
  work: buildTemplate("work"),
  minimal: buildTemplate("minimal"),
};

export const FIRST_RUN_TEMPLATE: TemplateName = "main";
