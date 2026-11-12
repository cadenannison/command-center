import { SOURCES, type SourceId } from "../lib/sources";
import type { Cells, GridWidgetKind, Tier, WidgetDefinition, WidgetId } from "./types";

const TASK_SOURCES = ["canvas", "ls", "gmail", "manual"] as const;
const DEEP: Pick<WidgetDefinition, "min" | "max" | "tiers"> = {
  min: { w: 3, h: 5 },
  max: { w: 12, h: 16 },
  tiers: { w: [3, 6], h: [5, 9] },
};

/** The widgets in the size table of docs/design/spec.md (decision 0331). Sizes live here and nowhere else. */
export const WIDGETS: readonly WidgetDefinition[] = [
  {
    id: "needs_me",
    kind: "needs_me",
    title: "Needs me",
    allowedSources: ["cal", "canvas", "ls", "gmail", "manual"],
    defaultSources: ["cal", "canvas", "ls", "gmail", "manual"],
    ...DEEP,
  },
  { id: "tasks", kind: "tasks", title: "Tasks", allowedSources: TASK_SOURCES, defaultSources: ["canvas", "ls", "manual"], ...DEEP },
  { id: "events", kind: "events", title: "Events", allowedSources: ["cal"], defaultSources: ["cal"], ...DEEP },
  { id: "canvas", kind: "tasks", title: "Canvas", allowedSources: ["canvas"], defaultSources: ["canvas"], ...DEEP },
  { id: "learningsuite", kind: "tasks", title: "LearningSuite", allowedSources: ["ls"], defaultSources: ["ls"], ...DEEP },
  { id: "owed_replies", kind: "tasks", title: "Owed replies", allowedSources: ["gmail"], defaultSources: ["gmail"], ...DEEP },
  { id: "my_tasks", kind: "tasks", title: "My tasks", allowedSources: ["manual"], defaultSources: ["manual"], ...DEEP },
  {
    id: "week",
    kind: "week",
    title: "This week",
    allowedSources: ["cal", "canvas", "ls", "gmail", "manual"],
    defaultSources: ["cal"],
    min: { w: 3, h: 4 },
    max: { w: 12, h: 10 },
    tiers: { w: [3, 6], h: [4, 7] },
  },
  {
    id: "weather",
    kind: "weather",
    title: "Weather",
    allowedSources: ["wx"],
    defaultSources: ["wx"],
    min: { w: 2, h: 3 },
    max: { w: 6, h: 9 },
    tiers: { w: [2, 4], h: [4, 6] },
  },
];

const BY_ID = new Map<string, WidgetDefinition>(WIDGETS.map((d) => [d.id, d]));

export function getWidget(id: string): WidgetDefinition | undefined {
  return BY_ID.get(id);
}

export function isWidgetId(id: string): id is WidgetId {
  return BY_ID.has(id);
}

function tierOf(value: number, [first, second]: readonly [number, number]): Tier {
  if (value <= first) return 1;
  return value <= second ? 2 : 3;
}

/** Width and height tiers (1 to 3) for a size in grid cells, exactly per the spec table. */
export function tier(w: number, h: number, def: WidgetDefinition): { readonly w: Tier; readonly h: Tier } {
  return { w: tierOf(w, def.tiers.w), h: tierOf(h, def.tiers.h) };
}

export type SizePreset = "S" | "M" | "L";

export const PRESETS: Readonly<Record<SizePreset, Cells>> = {
  S: { w: 3, h: 5 },
  M: { w: 4, h: 8 },
  L: { w: 7, h: 10 },
};

export function clampSize(size: Cells, def: WidgetDefinition): Cells {
  return {
    w: Math.min(Math.max(size.w, def.min.w), def.max.w),
    h: Math.min(Math.max(size.h, def.min.h), def.max.h),
  };
}

/** S 3x5, M 4x8, L 7x10, clamped to the widget's min and max. */
export function preset(name: SizePreset, def: WidgetDefinition): Cells {
  return clampSize(PRESETS[name], def);
}

export type SourceKind = "events" | "tasks" | "weather";

/** The kind a source feeds. Owed replies (gmail) count as tasks only while their toggle is on. */
export function kindOfSource(source: SourceId, owedAsTasks: boolean): SourceKind | null {
  switch (source) {
    case "cal":
      return "events";
    case "canvas":
    case "ls":
    case "manual":
      return "tasks";
    case "gmail":
      return owedAsTasks ? "tasks" : null;
    case "wx":
      return "weather";
  }
}

/** True when the sources may merge into one widget: one source, or all of one kind (decision 0331). */
export function canCombine(sources: readonly SourceId[], owedAsTasks: boolean): boolean {
  if (sources.length <= 1) return true;
  const kinds = new Set(sources.map((s) => kindOfSource(s, owedAsTasks)));
  return kinds.size === 1 && !kinds.has(null);
}

/** Needs me is the only widget that may hold sources of different kinds. */
export function isCrossKind(kind: GridWidgetKind): boolean {
  return kind === "needs_me";
}

/** Sources in registry order, the canonical order stored in a layout. */
export const SOURCE_ORDER: readonly SourceId[] = SOURCES.map((s) => s.id);
