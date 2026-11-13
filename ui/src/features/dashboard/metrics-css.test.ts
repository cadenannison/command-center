import { describe, expect, it } from "vitest";
import { cssRectOf, metricsFor } from "./metrics";

// Left and width are percentages of the container, so a widget cannot be wider than the page for a render after the
// window shrinks (card E2f). Evaluate the calc() for a container width and check the edges.
function px(expression: string, container: number): number {
  const m = /^calc\(\(100% - ([\d.]+)px\) \* (\d+) \/ (\d+) \+ ([\d.]+)px\)$/.exec(expression);
  if (!m) throw new Error(`unexpected expression ${expression}`);
  const [, gaps, cells, cols, plus] = m.map(Number);
  return ((container - Number(gaps)) * Number(cells)) / Number(cols) + Number(plus);
}

describe("cssRectOf", () => {
  it.each([
    [12, 70],
    [12, 100],
    [12, 130],
    [8, 130],
    [4, 130],
  ])("keeps every widget inside the container at %i columns and zoom %i", (cols, zoom) => {
    const m = metricsFor(1000, cols, zoom);
    for (const container of [320, 1068, 1800]) {
      for (let w = 1; w <= cols; w += 1) {
        for (let x = 0; x + w <= cols; x += 1) {
          const r = cssRectOf({ x, y: 0, w, h: 1 }, m);
          expect(px(r.left, container) + px(r.width, container)).toBeLessThanOrEqual(container + 1e-6);
          if (x + w === cols) expect(px(r.left, container) + px(r.width, container)).toBeCloseTo(container, 6);
        }
      }
    }
  });

  it("does not depend on the measured width, so a stale measurement cannot widen a widget", () => {
    const wide = cssRectOf({ x: 7, y: 0, w: 5, h: 10 }, metricsFor(1800, 12, 130));
    const narrow = cssRectOf({ x: 7, y: 0, w: 5, h: 10 }, metricsFor(300, 12, 130));
    expect(wide.left).toBe(narrow.left);
    expect(wide.width).toBe(narrow.width);
  });

  it("keeps rows in px and never shrinks a stretched widget below one row", () => {
    const m = metricsFor(1000, 12, 100);
    const r = cssRectOf({ x: 0, y: 2, w: 3, h: 2 }, m, { growX: 0, growY: -9999 });
    expect(r.top).toBe(2 * (m.rowPx + m.gapPx));
    expect(r.height).toBe(m.rowPx);
    expect(r.width.startsWith("max(")).toBe(true);
  });
});
