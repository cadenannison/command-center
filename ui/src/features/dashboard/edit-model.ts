import { sourceName } from "../../components/ui/source-dot";
import {
  MAX_ITEMS,
  PRESETS,
  WIDGETS,
  bottom,
  clampSize,
  getWidget,
  preset,
  type GridWidgetKind,
  type Layout,
  type LayoutItem,
  type SizePreset,
  type WidgetDefinition,
} from "../../layout";
import { MAX_Y } from "../../layout/sanitize-grid";
import { layoutToWire } from "./wire";

/** One line per widget kind. A new kind fails to compile here, so the gallery cannot silently lack a description. */
const KIND_BLURB: Readonly<Record<GridWidgetKind, string>> = {
  needs_me: "Everything that needs you next, across all your sources.",
  tasks: "Open tasks grouped by when they are due.",
  events: "Today's calendar events in time order.",
  week: "The days of this week at a glance.",
  weather: "High, low and outlook for the day.",
};

export interface GalleryEntry {
  readonly widgetId: string;
  readonly name: string;
  readonly kind: GridWidgetKind;
  readonly description: string;
  /** What addWidget gives a new widget: the M preset clamped to the widget's limits. */
  readonly size: { readonly w: number; readonly h: number };
}

function describe(def: WidgetDefinition): string {
  const sources = def.defaultSources.map(sourceName).join(", ");
  return `${KIND_BLURB[def.kind]} Starts with ${sources}.`;
}

/** The gallery rows, straight from the registry: a widget added there appears here with no other change. */
export function galleryEntries(): readonly GalleryEntry[] {
  return WIDGETS.map((def) => ({
    widgetId: def.id,
    name: def.title,
    kind: def.kind,
    description: describe(def),
    size: preset("M", def),
  }));
}

export const sizeText = (size: { readonly w: number; readonly h: number }): string => `${String(size.w)}×${String(size.h)}`;

/**
 * The registry sets no limit on how many widgets share an id: a dashboard may hold two Events widgets. What it does
 * limit is the number of items (MAX_ITEMS), the bottom edge (MAX_Y) and unique item ids. Past either limit the
 * sanitizer would drop the new item on the next load, so the gallery refuses it here.
 */
export function addBlocker(layout: Layout, widgetId: string): string | null {
  const def = getWidget(widgetId);
  if (!def) return "That widget is not available.";
  if (layout.items.length >= MAX_ITEMS) return `A dashboard holds at most ${String(MAX_ITEMS)} widgets. Remove one first.`;
  if (bottom(layout) + preset("M", def).h > MAX_Y) return "There is no room left below the other widgets.";
  return null;
}

/** An item id not used in the layout: `<widgetId>-<n>`, the same shape the templates use. Never reuses a number in use. */
export function nextItemId(layout: Layout, widgetId: string): string {
  const used = new Set(layout.items.map((i) => i.id));
  let n = 1;
  for (const id of used) {
    const match = new RegExp(`^${widgetId}-(\\d+)$`).exec(id);
    if (match?.[1]) n = Math.max(n, Number(match[1]) + 1);
  }
  while (used.has(`${widgetId}-${String(n)}`)) n += 1;
  return `${widgetId}-${String(n)}`;
}

export interface PresetState {
  readonly name: SizePreset;
  readonly size: { readonly w: number; readonly h: number };
  readonly disabled: boolean;
  /** Why it is disabled, in words a menu can show. */
  readonly reason: string | null;
}

/** Whether a size preset can be applied to an item, and if not why (pinned, outside min and max, or already that size). */
export function presetState(item: LayoutItem, name: SizePreset): PresetState {
  const def = getWidget(item.widgetId);
  const wanted = PRESETS[name];
  const size = def ? clampSize(wanted, def) : wanted;
  const state = (reason: string | null): PresetState => ({ name, size: wanted, disabled: reason !== null, reason });
  if (!def) return state("This widget cannot be resized.");
  if (item.pinned) return state("Unpin it to resize.");
  if (size.w !== wanted.w || size.h !== wanted.h) {
    return state(`${def.title} is limited to ${sizeText(def.min)} up to ${sizeText(def.max)}.`);
  }
  if (item.w === wanted.w && item.h === wanted.h) return state("Already this size.");
  return state(null);
}

/** The stored v1 layout document as JSON, and the file name it is saved under. Nothing else goes in the file. */
export function exportDocument(
  dashboardName: string,
  layout: Layout,
): { readonly filename: string; readonly content: string } {
  const slug =
    dashboardName
      .normalize("NFC")
      .replace(/[^\p{L}\p{N}._-]+/gu, "-")
      .replace(/^[-.]+|[-.]+$/g, "")
      .slice(0, 60)
      .replace(/-+$/, "") || "dashboard";
  return {
    filename: `command-center-${slug}-layout.json`,
    content: `${JSON.stringify(layoutToWire(layout), null, 2)}\n`,
  };
}
