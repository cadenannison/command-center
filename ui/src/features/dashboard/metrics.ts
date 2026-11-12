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
