import type { SourceId } from "../lib/sources";

/** Widget kinds (decision 0331). `summary` is pinned above the grid and is not a grid widget. */
export type WidgetKind = "events" | "tasks" | "weather" | "summary" | "week" | "needs_me";
export type GridWidgetKind = Exclude<WidgetKind, "summary">;

/** Persisted widget ids. Permanent once shipped (AGENTS.md): deprecate, never rename. */
export type WidgetId =
  | "needs_me"
  | "tasks"
  | "events"
  | "canvas"
  | "learningsuite"
  | "owed_replies"
  | "my_tasks"
  | "week"
  | "weather";

export type Tier = 1 | 2 | 3;

export interface Cells {
  readonly w: number;
  readonly h: number;
}

/** Tier 1 ends at `[0]`, tier 2 ends at `[1]`, anything larger is tier 3 (grid cells, not pixels). */
export interface TierThresholds {
  readonly w: readonly [number, number];
  readonly h: readonly [number, number];
}

export interface WidgetDefinition {
  readonly id: WidgetId;
  readonly kind: GridWidgetKind;
  readonly title: string;
  readonly allowedSources: readonly SourceId[];
  /** Sources a new widget starts with. A subset of `allowedSources`. */
  readonly defaultSources: readonly SourceId[];
  readonly min: Cells;
  readonly max: Cells;
  readonly tiers: TierThresholds;
}

export type OptionValue = string | number | boolean;

export const LAYOUT_VERSION = 1;

/** One placed widget. Coordinates are 0-based grid cells; x and y are the top-left corner. */
export interface LayoutItem {
  readonly id: string;
  readonly widgetId: WidgetId;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly pinned: boolean;
  readonly sources: readonly SourceId[];
  readonly options: Readonly<Record<string, OptionValue>>;
}

/** The persisted layout. Its keys are permanent (decision 0331). */
export interface Layout {
  readonly version: typeof LAYOUT_VERSION;
  readonly items: readonly LayoutItem[];
}
