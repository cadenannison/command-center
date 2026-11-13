import { clampZoom, type LayoutItem } from "../../layout";

export const ROW_UNIT_PX = 40;
export const GAP_PX = 14;

export interface Metrics {
  readonly cols: number;
  /** Width of one column in px at the current container width. */
  readonly colPx: number;
  readonly rowPx: number;
  readonly gapPx: number;
}

/** Zoom scales the row unit and the gap; the columns always share the container width. */
export function metricsFor(containerPx: number, cols: number, zoom: number): Metrics {
  const scale = clampZoom(zoom) / 100;
  const gapPx = GAP_PX * scale;
  const colPx = Math.max((containerPx - gapPx * (cols - 1)) / cols, 1);
  return { cols, colPx, rowPx: ROW_UNIT_PX * scale, gapPx };
}

export interface Rect {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
}

type Cells = Pick<LayoutItem, "x" | "y" | "w" | "h">;

export function rectOf(c: Cells, m: Metrics): Rect {
  return {
    left: c.x * (m.colPx + m.gapPx),
    top: c.y * (m.rowPx + m.gapPx),
    width: c.w * m.colPx + (c.w - 1) * m.gapPx,
    height: c.h * m.rowPx + (c.h - 1) * m.gapPx,
  };
}

/** The horizontal span of `cells` columns starting at column `x`, as a CSS length that follows the container's own width
 *  (100%) instead of a measured pixel number. Columns share the container, so x + w <= cols puts the right edge at or
 *  inside 100% by construction, with no render in between where a stale pixel width could push past the viewport. */
function span(x: number, cells: number, m: Metrics, shiftPx = 0): string {
  const gaps = m.gapPx * (m.cols - 1);
  return `calc((100% - ${String(gaps)}px) * ${String(cells)} / ${String(m.cols)} + ${String(x * m.gapPx + shiftPx)}px)`;
}

export interface CssRect {
  readonly left: string;
  readonly top: number;
  readonly width: string;
  readonly height: number;
}

/** What a lifted widget is shifted or stretched by while the pointer is down, in px. */
export interface Travel {
  readonly moveX?: number;
  readonly moveY?: number;
  readonly growX?: number;
  readonly growY?: number;
}

/** `rectOf` for the page: left and width are percentage based (see `span`), top and height stay in px because rows do
 *  not depend on the container width. A resize never goes below one cell. */
export function cssRectOf(c: Cells, m: Metrics, t: Travel = {}): CssRect {
  const width = span(c.w - 1, c.w, m, t.growX ?? 0);
  return {
    left: span(c.x, c.x, m, t.moveX ?? 0),
    top: c.y * (m.rowPx + m.gapPx) + (t.moveY ?? 0),
    width: t.growX === undefined ? width : `max(${String(m.colPx)}px, ${width})`,
    height: Math.max(c.h * m.rowPx + (c.h - 1) * m.gapPx + (t.growY ?? 0), t.growY === undefined ? 0 : m.rowPx),
  };
}

/** Whole cells covered by a pointer travel of `dx` and `dy` px (rounded to the nearest cell). */
export function cellsMoved(dx: number, dy: number, m: Metrics): { readonly dx: number; readonly dy: number } {
  return {
    dx: Math.round(dx / (m.colPx + m.gapPx)),
    dy: Math.round(dy / (m.rowPx + m.gapPx)),
  };
}

export function gridHeight(rows: number, m: Metrics): number {
  return rows <= 0 ? 0 : rows * m.rowPx + (rows - 1) * m.gapPx;
}
