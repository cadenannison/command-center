import { describe, expect, it } from "vitest";
import { canCombine, getWidget, isWidgetId, kindOfSource, preset, tier, WIDGETS } from "./registry";
import type { WidgetDefinition, WidgetId } from "./types";

const def = (id: WidgetId): WidgetDefinition => {
  const d = getWidget(id);
  if (!d) throw new Error(`missing ${id}`);
  return d;
};

// Written out from docs/design/spec.md (Size rules), not read from the registry.
const DEEP_IDS: WidgetId[] = ["needs_me", "tasks", "events", "canvas", "learningsuite", "owed_replies", "my_tasks"];
const TABLE: { ids: WidgetId[]; min: [number, number]; max: [number, number]; w: [number, number]; h: [number, number] }[] = [
  { ids: DEEP_IDS, min: [3, 5], max: [12, 16], w: [3, 6], h: [5, 9] },
  { ids: ["week"], min: [3, 4], max: [12, 10], w: [3, 6], h: [4, 7] },
  { ids: ["weather"], min: [2, 3], max: [6, 9], w: [2, 4], h: [4, 6] },
];

describe("registry", () => {
  it("registers exactly the widgets in the spec's size table", () => {
    expect(WIDGETS.map((w) => w.id).sort()).toEqual(
      ["canvas", "events", "learningsuite", "my_tasks", "needs_me", "owed_replies", "tasks", "weather", "week"].sort(),
    );
  });

  it("does not register Summary as a grid widget", () => {
    expect(isWidgetId("summary")).toBe(false);
    expect(WIDGETS.some((w) => (w.kind as string) === "summary")).toBe(false);
  });

  it.each(TABLE.flatMap((row) => row.ids.map((id) => [id, row] as const)))("%s has the spec's min and max", (id, row) => {
    expect(def(id).min).toEqual({ w: row.min[0], h: row.min[1] });
    expect(def(id).max).toEqual({ w: row.max[0], h: row.max[1] });
  });

  it("gives each widget its kind", () => {
    expect(WIDGETS.map((w) => [w.id, w.kind])).toEqual([
      ["needs_me", "needs_me"],
      ["tasks", "tasks"],
      ["events", "events"],
      ["canvas", "tasks"],
      ["learningsuite", "tasks"],
      ["owed_replies", "tasks"],
      ["my_tasks", "tasks"],
      ["week", "week"],
      ["weather", "weather"],
    ]);
  });

  it("lists default sources that are allowed sources", () => {
    for (const w of WIDGETS) {
      expect(w.defaultSources.length).toBeGreaterThan(0);
      for (const s of w.defaultSources) expect(w.allowedSources).toContain(s);
    }
  });
});

describe("tier", () => {
  describe.each(TABLE.flatMap((row) => row.ids.map((id) => [id, row] as const)))("%s", (id, row) => {
    const d = def(id);
    const [w1, w2] = row.w;
    const [h1, h2] = row.h;
    it("width tier changes exactly at each edge", () => {
      expect(tier(1, 1, d).w).toBe(1);
      expect(tier(w1, 1, d).w).toBe(1);
      expect(tier(w1 + 1, 1, d).w).toBe(2);
      expect(tier(w2, 1, d).w).toBe(2);
      expect(tier(w2 + 1, 1, d).w).toBe(3);
      expect(tier(row.max[0], 1, d).w).toBe(3);
    });
    it("height tier changes exactly at each edge", () => {
      expect(tier(1, 1, d).h).toBe(1);
      expect(tier(1, h1, d).h).toBe(1);
      expect(tier(1, h1 + 1, d).h).toBe(2);
      expect(tier(1, h2, d).h).toBe(2);
      expect(tier(1, h2 + 1, d).h).toBe(3);
      expect(tier(1, row.max[1], d).h).toBe(3);
    });
    it("the two tiers are independent (all nine combinations)", () => {
      const seen = new Set<string>();
      for (const w of [w1, w1 + 1, w2 + 1]) for (const h of [h1, h1 + 1, h2 + 1]) seen.add(JSON.stringify(tier(w, h, d)));
      expect(seen.size).toBe(9);
    });
  });
});

describe("preset", () => {
  it("gives S 3x5, M 4x8 and L 7x10 where they fit", () => {
    const d = def("tasks");
    expect(preset("S", d)).toEqual({ w: 3, h: 5 });
    expect(preset("M", d)).toEqual({ w: 4, h: 8 });
    expect(preset("L", d)).toEqual({ w: 7, h: 10 });
  });

  it("clamps to the widget's max", () => {
    expect(preset("L", def("weather"))).toEqual({ w: 6, h: 9 });
    expect(preset("M", def("weather"))).toEqual({ w: 4, h: 8 });
    expect(preset("L", def("week"))).toEqual({ w: 7, h: 10 });
  });

  it("never goes below a widget's min", () => {
    for (const d of WIDGETS) {
      for (const p of ["S", "M", "L"] as const) {
        const size = preset(p, d);
        expect(size.w).toBeGreaterThanOrEqual(d.min.w);
        expect(size.h).toBeGreaterThanOrEqual(d.min.h);
        expect(size.w).toBeLessThanOrEqual(d.max.w);
        expect(size.h).toBeLessThanOrEqual(d.max.h);
      }
    }
  });
});

describe("kind rule", () => {
  it("merges within one kind", () => {
    expect(canCombine(["canvas", "ls"], false)).toBe(true);
    expect(canCombine(["canvas", "ls", "manual"], false)).toBe(true);
  });

  it("refuses to merge across kinds", () => {
    expect(canCombine(["cal", "canvas"], true)).toBe(false);
    expect(canCombine(["wx", "cal"], true)).toBe(false);
    expect(canCombine(["wx", "manual"], true)).toBe(false);
  });

  it("counts owed replies (gmail) as tasks only when the toggle is on", () => {
    expect(kindOfSource("gmail", true)).toBe("tasks");
    expect(kindOfSource("gmail", false)).toBeNull();
    expect(canCombine(["gmail", "canvas"], true)).toBe(true);
    expect(canCombine(["gmail", "canvas"], false)).toBe(false);
    expect(canCombine(["gmail", "cal"], true)).toBe(false);
  });

  it("has nothing to merge for zero or one source", () => {
    expect(canCombine([], false)).toBe(true);
    expect(canCombine(["gmail"], false)).toBe(true);
  });

  it("makes needs_me the only widget that allows more than one kind", () => {
    for (const w of WIDGETS) {
      const kinds = new Set(w.allowedSources.map((s) => kindOfSource(s, true)));
      if (w.id === "needs_me") expect(kinds.size).toBeGreaterThan(1);
      else if (w.kind === "tasks") expect(kinds.size).toBe(1);
    }
  });
});
