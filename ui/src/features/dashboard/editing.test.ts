import { describe, expect, it } from "vitest";
import { describeChange, itemOf, keyboardStep, pointerMove, pointerResize, tierLabel } from "./editing";
import { cellsMoved, metricsFor, rectOf } from "./metrics";
import { MINIMAL } from "./test-support";

const NEEDS = "needs_me-1";
const EVENTS = "events-2";

describe("metrics", () => {
  it("splits the width into columns with a 14px gap at 100 percent", () => {
    const m = metricsFor(1200, 12, 100);
    expect(m.gapPx).toBe(14);
    expect(m.rowPx).toBe(40);
    expect(m.colPx * 12 + 14 * 11).toBeCloseTo(1200);
  });
  it("scales the row unit and the gap with the zoom", () => {
    const m = metricsFor(1200, 12, 130);
    expect(m.rowPx).toBeCloseTo(52);
    expect(m.gapPx).toBeCloseTo(18.2);
  });
  it("clamps the zoom to 70 to 130 percent", () => {
    expect(metricsFor(1200, 12, 10).rowPx).toBeCloseTo(28);
    expect(metricsFor(1200, 12, 900).rowPx).toBeCloseTo(52);
  });
  it("places a cell rectangle from its column and row", () => {
    const m = metricsFor(1200, 12, 100);
    const r = rectOf({ x: 1, y: 2, w: 2, h: 3 }, m);
    expect(r.left).toBeCloseTo(m.colPx + 14);
    expect(r.top).toBe(2 * 54);
    expect(r.height).toBe(3 * 40 + 2 * 14);
  });
  it("rounds pointer travel to whole cells", () => {
    const m = metricsFor(1200, 12, 100);
    expect(cellsMoved(m.colPx + 14 + 10, -(54 * 2) + 5, m)).toEqual({
      dx: 1,
      dy: -2,
    });
    expect(cellsMoved(10, 10, m)).toEqual({ dx: 0, dy: 0 });
  });
});

describe("keyboardStep", () => {
  it("moves an item one cell with an arrow", () => {
    const next = keyboardStep(MINIMAL, EVENTS, "ArrowLeft", false, 12);
    expect(itemOf(next, EVENTS)?.x).toBe(6);
  });
  it("resizes an item one cell with Shift and an arrow", () => {
    const next = keyboardStep(MINIMAL, NEEDS, "ArrowLeft", true, 12);
    expect(itemOf(next, NEEDS)).toMatchObject({ w: 6, x: 0 });
  });
  it("does not move an item past the right edge", () => {
    const next = keyboardStep(MINIMAL, EVENTS, "ArrowRight", false, 12);
    expect(itemOf(next, EVENTS)?.x).toBe(7);
  });
  it("does not change a pinned item", () => {
    const pinned = {
      ...MINIMAL,
      items: MINIMAL.items.map((i) => (i.id === EVENTS ? { ...i, pinned: true } : i)),
    };
    expect(keyboardStep(pinned, EVENTS, "ArrowLeft", false, 12)).toBe(pinned);
  });
});

describe("pointer edits", () => {
  it("moves by the cells the pointer travelled", () => {
    expect(itemOf(pointerMove(MINIMAL, EVENTS, -1, 0, 12), EVENTS)?.x).toBe(6);
  });
  it("resizes by the cells the pointer travelled", () => {
    expect(itemOf(pointerResize(MINIMAL, NEEDS, -1, 1, 12), NEEDS)).toMatchObject({ w: 6, h: 11 });
  });
});

describe("labels and announcements", () => {
  it("shows the tier badge as in the spec", () => {
    expect(tierLabel({ widgetId: "needs_me", w: 5, h: 10 })).toMatch(/^W\d · H\d · 5×10$/);
  });
  it("says where an item moved, one-based", () => {
    const before = itemOf(MINIMAL, EVENTS);
    const after = itemOf(keyboardStep(MINIMAL, EVENTS, "ArrowLeft", false, 12), EVENTS);
    expect(describeChange("Events", before, after, false)).toBe("Events moved to column 7, row 1.");
  });
  it("says when a move changed nothing", () => {
    const before = itemOf(MINIMAL, EVENTS);
    expect(describeChange("Events", before, before, false)).toBe("Events cannot move further: column 8, row 1.");
  });
  it("says the new size after a resize", () => {
    const before = itemOf(MINIMAL, NEEDS);
    const after = itemOf(keyboardStep(MINIMAL, NEEDS, "ArrowLeft", true, 12), NEEDS);
    expect(describeChange("Needs me", before, after, true)).toBe("Needs me resized to 6 wide, 10 tall.");
  });
  it("says a pinned item cannot change", () => {
    const pinned = MINIMAL.items.map((i) => ({ ...i, pinned: true })).find((i) => i.id === EVENTS);
    expect(describeChange("Events", pinned, pinned, false)).toBe("Events is pinned and cannot move or resize.");
  });
});
