import { describe, expect, it } from "vitest";
import { addWidget, autoArrange, clampZoom, columnsForWidth, compact, fitToColumns, hasOverlap, move, overlaps, place, remove, resize, setPinned } from "./grid";
import { getWidget, WIDGETS } from "./registry";
import type { Layout, LayoutItem } from "./types";
import { int, item, layoutOf, rng } from "./fixtures";

const byId = (l: Layout, id: string): LayoutItem => {
  const found = l.items.find((i) => i.id === id);
  if (!found) throw new Error(`no ${id}`);
  return found;
};
const inBounds = (l: Layout, cols: number): boolean => l.items.every((i) => i.x >= 0 && i.y >= 0 && i.x + i.w <= cols);

describe("columnsForWidth and clampZoom", () => {
  it("picks 12, 8 or 4 columns at the edges", () => {
    expect([1400, 1200, 1199, 800, 799, 400, 0].map(columnsForWidth)).toEqual([12, 12, 8, 8, 4, 4, 4]);
  });
  it("clamps zoom to 70 to 130", () => {
    expect([50, 69, 70, 100, 130, 131, 500].map(clampZoom)).toEqual([70, 70, 70, 100, 130, 130, 130]);
    expect(clampZoom(Number.NaN)).toBe(100);
    expect(clampZoom(Number.POSITIVE_INFINITY)).toBe(100);
  });
});

describe("overlaps", () => {
  it("treats touching edges as not overlapping", () => {
    expect(overlaps({ x: 0, y: 0, w: 3, h: 3 }, { x: 3, y: 0, w: 3, h: 3 })).toBe(false);
    expect(overlaps({ x: 0, y: 0, w: 3, h: 3 }, { x: 0, y: 3, w: 3, h: 3 })).toBe(false);
    expect(overlaps({ x: 0, y: 0, w: 3, h: 3 }, { x: 2, y: 2, w: 3, h: 3 })).toBe(true);
  });
});

describe("place and addWidget", () => {
  it("pushes items below the new one down to make room", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5));
    const next = place(l, item("b", "events", 0, 0, 4, 5), 12);
    expect(byId(next, "b").y).toBe(0);
    expect(byId(next, "a").y).toBe(5);
    expect(hasOverlap(next.items)).toBe(false);
  });

  it("clamps the new item to its widget's limits and the columns", () => {
    const next = place(layoutOf(), item("w", "weather", 11, 0, 20, 20), 12);
    expect(byId(next, "w")).toMatchObject({ w: 6, h: 9, x: 6 });
  });

  it("ignores a duplicate id or an unknown widget", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5));
    expect(place(l, item("a", "events", 4, 0, 4, 5), 12)).toBe(l);
    expect(place(l, { ...item("z", "tasks", 4, 0, 4, 5), widgetId: "nope" as never }, 12)).toBe(l);
  });

  it("adds a widget at the M preset below everything", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5));
    const next = addWidget(l, "weather", "w", 12);
    expect(byId(next, "w")).toMatchObject({ x: 0, y: 5, w: 4, h: 8, sources: ["wx"], pinned: false });
    expect(addWidget(l, "nope", "x", 12)).toBe(l);
  });
});

describe("move", () => {
  it("moves an item and pushes the item it lands on down", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5), item("b", "events", 4, 0, 4, 5));
    const next = move(l, "a", 4, 0, 12);
    expect(byId(next, "a")).toMatchObject({ x: 4, y: 0 });
    expect(byId(next, "b")).toMatchObject({ x: 4, y: 5 });
  });

  it("clamps to the columns and to the top", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5));
    expect(byId(move(l, "a", 99, -3, 12), "a")).toMatchObject({ x: 8, y: 0 });
    expect(byId(move(l, "a", 99, 0, 4), "a")).toMatchObject({ x: 0 });
  });

  it("leaves unknown ids alone and does not mutate its input", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5));
    const copy = JSON.stringify(l);
    expect(move(l, "nope", 1, 1, 12)).toBe(l);
    move(l, "a", 5, 5, 12);
    expect(JSON.stringify(l)).toBe(copy);
  });
});

describe("pinned items", () => {
  it("do not move, and unpinned items flow around them", () => {
    const l = layoutOf(item("p", "tasks", 0, 0, 4, 5, true), item("a", "events", 4, 0, 4, 5));
    expect(move(l, "p", 8, 8, 12)).toBe(l);
    const next = move(l, "a", 0, 0, 12);
    expect(byId(next, "p")).toMatchObject({ x: 0, y: 0 });
    expect(byId(next, "a")).toMatchObject({ x: 0, y: 5 });
  });

  it("cannot be resized or removed by pushing, only by their own commands", () => {
    const l = layoutOf(item("p", "tasks", 0, 0, 4, 5, true));
    expect(resize(l, "p", 6, 6, 12)).toBe(l);
    expect(remove(l, "p").items).toEqual([]);
  });

  it("setPinned changes only the flag", () => {
    const l = layoutOf(item("a", "tasks", 2, 3, 4, 5));
    expect(byId(setPinned(l, "a", true), "a")).toEqual({ ...byId(l, "a"), pinned: true });
    expect(byId(move(setPinned(l, "a", false), "a", 5, 5, 12), "a")).toMatchObject({ x: 5, y: 5 });
  });
});

describe("resize", () => {
  const l = layoutOf(item("a", "tasks", 0, 0, 4, 8), item("b", "events", 4, 0, 4, 5));
  it.each([
    [1, 1, 3, 5],
    [99, 99, 12, 16],
    [6, 9, 6, 9],
  ])("clamps %i x %i to min and max (%i x %i)", (w, h, ew, eh) => {
    expect(byId(resize(l, "a", w, h, 12), "a")).toMatchObject({ w: ew, h: eh });
  });

  it("clamps to the columns and pulls x back so the item stays inside", () => {
    const wide = layoutOf(item("a", "tasks", 6, 0, 6, 5));
    expect(byId(resize(wide, "a", 12, 5, 8), "a")).toMatchObject({ x: 0, w: 8 });
  });

  it("clamps weather to its own, smaller, limits", () => {
    const wx = layoutOf(item("w", "weather", 0, 0, 3, 5));
    expect(byId(resize(wx, "w", 1, 1, 12), "w")).toMatchObject({ w: 2, h: 3 });
    expect(byId(resize(wx, "w", 12, 12, 12), "w")).toMatchObject({ w: 6, h: 9 });
  });

  it("pushes what it grows into down", () => {
    const next = resize(l, "a", 8, 8, 12);
    expect(byId(next, "b").y).toBe(8);
    expect(hasOverlap(next.items)).toBe(false);
  });
});

describe("compact", () => {
  it("never moves an item up and keeps the input order", () => {
    const l = layoutOf(item("a", "tasks", 0, 10, 4, 5), item("b", "events", 6, 3, 4, 5));
    expect(compact(l.items)).toEqual(l.items);
  });

  it("breaks ties by reading order (y, x, then id)", () => {
    const items = [item("b", "tasks", 0, 0, 4, 5), item("a", "events", 0, 0, 4, 5), item("c", "canvas", 2, 0, 4, 5)];
    const out = compact(items);
    expect(out.map((i) => [i.id, i.y])).toEqual([
      ["b", 5],
      ["a", 0],
      ["c", 10],
    ]);
  });
});

describe("autoArrange", () => {
  it("packs unpinned items densely in reading order", () => {
    const l = layoutOf(item("a", "tasks", 0, 20, 4, 5), item("b", "events", 6, 0, 4, 5), item("c", "canvas", 0, 8, 4, 5));
    const next = autoArrange(l, 12);
    expect(next.items.map((i) => [i.id, i.x, i.y])).toEqual([
      ["a", 8, 0],
      ["b", 0, 0],
      ["c", 4, 0],
    ]);
  });

  it("flows around pinned items", () => {
    const l = layoutOf(item("p", "tasks", 4, 0, 4, 5, true), item("a", "events", 0, 0, 4, 5), item("b", "canvas", 8, 0, 4, 5), item("c", "my_tasks", 0, 9, 4, 5));
    const next = autoArrange(l, 12);
    expect(byId(next, "p")).toMatchObject({ x: 4, y: 0 });
    expect(next.items.map((i) => [i.id, i.x, i.y])).toEqual([
      ["p", 4, 0],
      ["a", 0, 0],
      ["b", 8, 0],
      ["c", 0, 5],
    ]);
  });

  it("wraps to the next row when an item does not fit the columns left", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 7, 5), item("b", "events", 7, 0, 5, 5));
    const next = autoArrange(l, 8);
    expect(byId(next, "b")).toMatchObject({ x: 0, y: 5, w: 5 });
    expect(inBounds(next, 8)).toBe(true);
  });
});

describe("fitToColumns", () => {
  it("returns a valid 12-column layout unchanged in content", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5), item("b", "events", 4, 0, 8, 5));
    expect(fitToColumns(l, 12).items).toEqual(l.items);
  });

  it("clamps widths and pushes down at 4 columns, without overlaps", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 6, 5), item("b", "events", 6, 0, 6, 5), item("w", "weather", 10, 0, 2, 3));
    const next = fitToColumns(l, 4);
    expect(inBounds(next, 4)).toBe(true);
    expect(hasOverlap(next.items)).toBe(false);
    expect(byId(next, "a").w).toBe(4);
  });

  it("unpins an item in the view when clamping would make two pinned items overlap", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5, true), item("b", "events", 8, 0, 4, 5, true));
    const next = fitToColumns(l, 4);
    expect(hasOverlap(next.items)).toBe(false);
    expect(byId(next, "a")).toMatchObject({ x: 0, y: 0, pinned: true });
    expect(byId(next, "b").pinned).toBe(false);
  });
});

describe("randomized operation sequences (fixed seed)", () => {
  const ids = WIDGETS.map((w) => w.id);

  it.each([1, 2, 3, 12345, 99999])("never overlap, break a size limit or move a pinned item (seed %i)", (seed) => {
    const next = rng(seed);
    let layout = layoutOf();
    let counter = 0;
    for (let step = 0; step < 300; step++) {
      const cols = [12, 8, 4][int(next, 0, 2)] ?? 12;
      const existing = layout.items;
      const target = existing[int(next, 0, Math.max(existing.length - 1, 0))];
      const pinnedBefore = new Map(existing.filter((i) => i.pinned).map((i) => [i.id, i]));
      switch (int(next, 0, 6)) {
        case 0:
        case 1:
          if (existing.length < 20) layout = addWidget(layout, ids[int(next, 0, ids.length - 1)] ?? "tasks", `i${String((counter += 1))}`, cols);
          break;
        case 2:
          if (target) layout = move(layout, target.id, int(next, -3, 14), int(next, -3, 40), cols);
          break;
        case 3:
          if (target) layout = resize(layout, target.id, int(next, 0, 14), int(next, 0, 18), cols);
          break;
        case 4:
          if (target) layout = setPinned(layout, target.id, next() < 0.5);
          break;
        case 5:
          if (target && next() < 0.3) layout = remove(layout, target.id);
          break;
        default:
          if (next() < 0.2) layout = autoArrange(layout, cols);
      }
      expect(hasOverlap(layout.items)).toBe(false);
      for (const i of layout.items) {
        const def = getWidget(i.widgetId);
        expect(i.x).toBeGreaterThanOrEqual(0);
        expect(i.y).toBeGreaterThanOrEqual(0);
        expect(i.w).toBeGreaterThanOrEqual(def?.min.w ?? 0);
        expect(i.w).toBeLessThanOrEqual(def?.max.w ?? 0);
        expect(i.h).toBeGreaterThanOrEqual(def?.min.h ?? 0);
        expect(i.h).toBeLessThanOrEqual(def?.max.h ?? 0);
      }
      // An item that was pinned before this step and is still pinned has not moved.
      for (const [id, before] of pinnedBefore) {
        const now = layout.items.find((i) => i.id === id);
        if (now?.pinned) expect(now.x === before.x && now.y === before.y).toBe(true);
      }
    }
  });
});
