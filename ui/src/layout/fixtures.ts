import { getWidget } from "./registry";
import { LAYOUT_VERSION, type Layout, type LayoutItem, type WidgetId } from "./types";

export function item(id: string, widgetId: WidgetId, x: number, y: number, w: number, h: number, pinned = false): LayoutItem {
  const def = getWidget(widgetId);
  if (!def) throw new Error(`unknown ${widgetId}`);
  return { id, widgetId, x, y, w, h, pinned, sources: def.defaultSources, options: {} };
}

export const layoutOf = (...items: LayoutItem[]): Layout => ({ version: LAYOUT_VERSION, items });

/** Small deterministic generator (mulberry32) so randomized tests repeat exactly. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const int = (next: () => number, lo: number, hi: number): number => lo + Math.floor(next() * (hi - lo + 1));
