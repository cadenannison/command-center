import { describe, expect, it } from "vitest";
import { hasOverlap } from "./grid";
import { buildTemplate, DEFAULT_LAYOUTS, FIRST_RUN_TEMPLATE, TEMPLATE_ENTRIES, type TemplateName } from "./defaults";
import { canCombine, getWidget } from "./registry";
import { sanitizeLayout } from "./validate";

const names = Object.keys(TEMPLATE_ENTRIES) as TemplateName[];

describe("default layouts", () => {
  it("applies Main at first run", () => {
    expect(FIRST_RUN_TEMPLATE).toBe("main");
    expect(names.sort()).toEqual(["main", "minimal", "student", "work"]);
  });

  it.each(names)("%s is valid, overlap-free and unchanged by sanitize", (name) => {
    const layout = DEFAULT_LAYOUTS[name];
    expect(hasOverlap(layout.items)).toBe(false);
    const r = sanitizeLayout(layout);
    expect(r).toMatchObject({ ok: true, warnings: [] });
    if (r.ok) expect(r.layout).toEqual(layout);
  });

  it.each(names)("%s obeys the kind rule and the size limits", (name) => {
    for (const i of DEFAULT_LAYOUTS[name].items) {
      const def = getWidget(i.widgetId);
      expect(def).toBeDefined();
      if (def?.kind !== "needs_me") expect(canCombine(i.sources, true)).toBe(true);
      expect(i.w).toBeGreaterThanOrEqual(def?.min.w ?? 99);
      expect(i.w).toBeLessThanOrEqual(def?.max.w ?? 0);
      expect(i.x + i.w).toBeLessThanOrEqual(12);
      expect(i.pinned).toBe(false);
    }
  });

  it("places Main as two full rows", () => {
    expect(DEFAULT_LAYOUTS.main.items.map((i) => [i.widgetId, i.x, i.y, i.w, i.h])).toEqual([
      ["needs_me", 0, 0, 4, 10],
      ["tasks", 4, 0, 5, 10],
      ["events", 9, 0, 3, 10],
      ["week", 0, 10, 5, 6],
      ["owed_replies", 5, 10, 4, 6],
      ["weather", 9, 10, 3, 6],
    ]);
  });

  it("gives Student, Work and Minimal their widgets", () => {
    const ids = (n: TemplateName) => DEFAULT_LAYOUTS[n].items.map((i) => i.widgetId);
    expect(ids("student")).toEqual(["needs_me", "canvas", "learningsuite", "week", "events"]);
    expect(ids("work")).toEqual(["events", "owed_replies", "my_tasks", "weather"]);
    expect(ids("minimal")).toEqual(["needs_me", "events"]);
  });

  it("builds the same layout every time", () => {
    for (const n of names) expect(buildTemplate(n)).toEqual(DEFAULT_LAYOUTS[n]);
  });
});
