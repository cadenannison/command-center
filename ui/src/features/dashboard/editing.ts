import { getWidget, move, resize, tier, type Layout, type LayoutItem } from "../../layout";

export type Arrow = "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown";
export const ARROWS: readonly string[] = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];

const STEP: Record<Arrow, readonly [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

export const isArrow = (key: string): key is Arrow => ARROWS.includes(key);

export const itemOf = (layout: Layout, id: string): LayoutItem | undefined => layout.items.find((i) => i.id === id);

/** One keyboard step: arrows move by a cell, Shift plus arrows resize by a cell. */
export function keyboardStep(layout: Layout, id: string, key: Arrow, shift: boolean, cols: number): Layout {
  const item = itemOf(layout, id);
  if (!item) return layout;
  const [dx, dy] = STEP[key];
  return shift ? resize(layout, id, item.w + dx, item.h + dy, cols) : move(layout, id, item.x + dx, item.y + dy, cols);
}

export function pointerMove(base: Layout, id: string, dx: number, dy: number, cols: number): Layout {
  const item = itemOf(base, id);
  return item ? move(base, id, item.x + dx, item.y + dy, cols) : base;
}

export function pointerResize(base: Layout, id: string, dw: number, dh: number, cols: number): Layout {
  const item = itemOf(base, id);
  return item ? resize(base, id, item.w + dw, item.h + dh, cols) : base;
}

/** "W2 · H3 · 5×10": the tier badge an item shows in edit mode (spec, Widget anatomy). */
export function tierLabel(item: Pick<LayoutItem, "widgetId" | "w" | "h">): string {
  const def = getWidget(item.widgetId);
  const t = def ? tier(item.w, item.h, def) : null;
  const size = `${String(item.w)}×${String(item.h)}`;
  return t ? `W${String(t.w)} · H${String(t.h)} · ${size}` : size;
}

const place = (i: LayoutItem): string => `column ${String(i.x + 1)}, row ${String(i.y + 1)}`;
const sized = (i: LayoutItem): string => `${String(i.w)} wide, ${String(i.h)} tall`;

/** What a screen reader hears after a keyboard step. */
export function describeChange(
  title: string,
  before: LayoutItem | undefined,
  after: LayoutItem | undefined,
  resized: boolean,
): string {
  if (!before || !after) return `${title} cannot be changed.`;
  if (before.pinned) return `${title} is pinned and cannot move or resize.`;
  if (resized) {
    return before.w === after.w && before.h === after.h
      ? `${title} cannot be resized further: ${sized(after)}.`
      : `${title} resized to ${sized(after)}.`;
  }
  return before.x === after.x && before.y === after.y
    ? `${title} cannot move further: ${place(after)}.`
    : `${title} moved to ${place(after)}.`;
}

export const pickedUp = (title: string, i: LayoutItem): string =>
  `Picked up ${title} at ${place(i)}, ${sized(i)}. Arrow keys move, Shift and arrow keys resize, Enter drops, Escape cancels.`;
export const dropped = (title: string, i: LayoutItem): string => `Dropped ${title} at ${place(i)}, ${sized(i)}.`;
export const cancelled = (title: string, i: LayoutItem): string =>
  `Cancelled. ${title} is back at ${place(i)}, ${sized(i)}.`;
