import { clampSize, getWidget, preset } from "./registry";
import type { Layout, LayoutItem, WidgetDefinition } from "./types";

export const ZOOM_MIN = 70;
export const ZOOM_MAX = 130;

/** Smart scale: 12 columns on a full window, 8 or 4 on smaller ones (breakpoints: decision 0350). */
export function columnsForWidth(widthPx: number): 12 | 8 | 4 {
  if (widthPx >= 1200) return 12;
  if (widthPx >= 800) return 8;
  return 4;
}

/** Grid zoom in percent, clamped to 70 to 130. A non-finite value gives 100. */
export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return 100;
  return Math.min(Math.max(Math.round(zoom), ZOOM_MIN), ZOOM_MAX);
}

type Box = Pick<LayoutItem, "x" | "y" | "w" | "h">;

export function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

export function hasOverlap(items: readonly Box[]): boolean {
  return items.some((a, i) => items.slice(i + 1).some((b) => overlaps(a, b)));
}

const byReadingOrder = (a: LayoutItem, b: LayoutItem): number =>
  a.y - b.y || a.x - b.x || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/**
 * Push-down compaction (decision 0350). Pinned items stay where they are and are obstacles. The
 * `first` item (the one just placed, moved or resized) is settled next, then every other item in
 * reading order; an item that collides moves down to just below the item it hits. Nothing moves up.
 * Pinned items must not overlap each other. Output keeps the input's array order.
 */
export function compact(items: readonly LayoutItem[], firstId?: string): LayoutItem[] {
  const settled: LayoutItem[] = items.filter((i) => i.pinned);
  const pinned = new Set(settled.map((i) => i.id));
  const first = items.find((i) => i.id === firstId && !pinned.has(i.id));
  const rest = items.filter((i) => !pinned.has(i.id) && i !== first).sort(byReadingOrder);
  const moved = new Map<string, LayoutItem>();
  for (const item of first ? [first, ...rest] : rest) {
    let y = item.y;
    for (;;) {
      const hit = settled.find((s) => overlaps({ ...item, y }, s));
      if (!hit) break;
      y = hit.y + hit.h;
    }
    const placed = y === item.y ? item : { ...item, y };
    settled.push(placed);
    moved.set(item.id, placed);
  }
  return items.map((i) => moved.get(i.id) ?? i);
}

function withItems(layout: Layout, items: readonly LayoutItem[]): Layout {
  return { ...layout, items };
}

function clampItem(item: LayoutItem, def: WidgetDefinition, cols: number): LayoutItem {
  const size = clampSize({ w: item.w, h: item.h }, def);
  const w = Math.min(size.w, cols);
  const x = Math.min(Math.max(item.x, 0), cols - w);
  return { ...item, x, y: Math.max(item.y, 0), w, h: size.h };
}

/** Add an item at its stated spot, clamped to the widget's limits and the columns; others make room. */
export function place(layout: Layout, item: LayoutItem, cols: number): Layout {
  const def = getWidget(item.widgetId);
  if (!def || layout.items.some((i) => i.id === item.id)) return layout;
  const clamped = clampItem(item, def, cols);
  return withItems(layout, compact([...layout.items, clamped], clamped.id));
}

export function bottom(layout: Layout): number {
  return layout.items.reduce((max, i) => Math.max(max, i.y + i.h), 0);
}

/** Add a widget at its default sources and the M preset (clamped), below everything else. */
export function addWidget(layout: Layout, widgetId: string, id: string, cols: number): Layout {
  const def = getWidget(widgetId);
  if (!def) return layout;
  const size = preset("M", def);
  return place(
    layout,
    { id, widgetId: def.id, x: 0, y: bottom(layout), ...size, pinned: false, sources: def.defaultSources, options: {} },
    cols,
  );
}

function update(layout: Layout, id: string, change: (item: LayoutItem, def: WidgetDefinition) => LayoutItem): Layout {
  const item = layout.items.find((i) => i.id === id);
  const def = item && getWidget(item.widgetId);
  if (!item || !def || item.pinned) return layout;
  const next = change(item, def);
  return withItems(layout, compact(layout.items.map((i) => (i.id === id ? next : i)), id));
}

/** Move an item to a cell, clamped to the columns. A pinned item does not move (unpin it first). */
export function move(layout: Layout, id: string, x: number, y: number, cols: number): Layout {
  return update(layout, id, (item, def) => clampItem({ ...item, x, y }, def, cols));
}

/** Resize an item, clamped to its min, max and the columns. A pinned item does not resize. */
export function resize(layout: Layout, id: string, w: number, h: number, cols: number): Layout {
  return update(layout, id, (item, def) => clampItem({ ...item, w, h }, def, cols));
}

export function remove(layout: Layout, id: string): Layout {
  return withItems(layout, layout.items.filter((i) => i.id !== id));
}

/** Pin an item to its cell, or release it. Pinning never changes a position. */
export function setPinned(layout: Layout, id: string, pinned: boolean): Layout {
  return withItems(layout, layout.items.map((i) => (i.id === id ? { ...i, pinned } : i)));
}

/**
 * Even spacing (decision 0350): unpinned items, in reading order, each take the first free spot
 * scanning rows from the top and columns from the left, flowing around pinned items. No gaps are left
 * that an item below could fill.
 */
export function autoArrange(layout: Layout, cols: number): Layout {
  const fixed: LayoutItem[] = layout.items.filter((i) => i.pinned);
  const placed = new Map<string, LayoutItem>();
  const order = layout.items.filter((i) => !i.pinned).sort(byReadingOrder);
  for (const raw of order) {
    const def = getWidget(raw.widgetId);
    if (!def) continue;
    const item = clampItem(raw, def, cols);
    const taken = [...fixed, ...placed.values()];
    let spot: LayoutItem | undefined;
    for (let y = 0; !spot; y++) {
      for (let x = 0; x + item.w <= cols; x++) {
        const candidate = { ...item, x, y };
        if (!taken.some((t) => overlaps(candidate, t))) {
          spot = candidate;
          break;
        }
      }
    }
    placed.set(item.id, spot);
  }
  return withItems(layout, layout.items.map((i) => placed.get(i.id) ?? i));
}

/**
 * The layout as shown at a given column count (a view; do not store it). Widths and x are clamped to
 * the columns, then items are pushed down. At 12 columns a valid layout is returned unchanged.
 */
export function fitToColumns(layout: Layout, cols: number): Layout {
  const kept: LayoutItem[] = [];
  const fitted = [...layout.items].sort(byReadingOrder).map((i) => {
    const w = Math.min(i.w, cols);
    const next = { ...i, w, x: Math.min(i.x, cols - w) };
    // Clamping can make two pinned items overlap; the later one is unpinned in this view only.
    if (!next.pinned) return next;
    if (kept.some((k) => overlaps(k, next))) return { ...next, pinned: false };
    kept.push(next);
    return next;
  });
  const byId = new Map(fitted.map((i) => [i.id, i]));
  const original = layout.items.map((i) => byId.get(i.id) ?? i);
  return withItems(layout, compact(original));
}
