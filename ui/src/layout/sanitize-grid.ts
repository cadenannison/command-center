import { compact } from "./grid";
import type { LayoutItem, WidgetDefinition } from "./types";

export const COLUMNS = 12;
export const MAX_Y = 500;

/** Clamp a rounded box to the widget's limits on the 12-column grid (the stored layout's grid). */
export function clampItemTo12(
  def: WidgetDefinition,
  box: { x: number; y: number; w: number; h: number },
): { x: number; y: number; w: number; h: number } {
  const w = Math.min(Math.max(box.w, def.min.w), def.max.w);
  const h = Math.min(Math.max(box.h, def.min.h), def.max.h);
  return { x: Math.min(Math.max(box.x, 0), COLUMNS - w), y: Math.min(Math.max(box.y, 0), MAX_Y), w, h };
}

/**
 * Make items overlap-free: a pinned item that overlaps an earlier pinned one (reading order) is
 * unpinned, then the rest are pushed down around the pinned ones. Returns the ids it unpinned.
 */
export function compactForSanitize(items: readonly LayoutItem[]): { items: LayoutItem[]; unpinned: string[] } {
  const keptPinned: LayoutItem[] = [];
  const unpinned: string[] = [];
  const pinnedInOrder = items.filter((i) => i.pinned).sort((a, b) => a.y - b.y || a.x - b.x || (a.id < b.id ? -1 : 1));
  for (const item of pinnedInOrder) {
    const clash = keptPinned.some((k) => item.x < k.x + k.w && k.x < item.x + item.w && item.y < k.y + k.h && k.y < item.y + item.h);
    if (clash) unpinned.push(item.id);
    else keptPinned.push(item);
  }
  const fixed = items.map((i) => (unpinned.includes(i.id) ? { ...i, pinned: false } : i));
  return { items: compact(fixed), unpinned };
}
