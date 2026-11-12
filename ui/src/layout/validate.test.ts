import { describe, expect, it } from "vitest";
import { hasOverlap } from "./grid";
import { int, item, layoutOf, rng } from "./fixtures";
import { MAX_ITEMS, migrateLayout, parseLayoutJson, sanitizeLayout, serializeLayout, type LayoutResult, type Migrations } from "./validate";
import { buildTemplate, type TemplateName } from "./defaults";

const good = (r: LayoutResult) => {
  if (!r.ok) throw new Error(`expected ok, got ${r.error.code}`);
  return r;
};
const bad = (r: LayoutResult) => {
  if (r.ok) throw new Error("expected an error");
  return r.error.code;
};
const raw = (items: unknown[], version: unknown = 1) => ({ version, items });
const rawItem = (over: Record<string, unknown> = {}) => ({
  id: "a",
  widgetId: "tasks",
  x: 0,
  y: 0,
  w: 4,
  h: 8,
  pinned: false,
  sources: ["canvas", "ls", "manual"],
  options: {},
  ...over,
});

describe("versions", () => {
  it("accepts version 1", () => {
    expect(good(sanitizeLayout(raw([rawItem()]))).layout.items).toHaveLength(1);
  });

  it.each([[null], ["1"], [1.5]])("rejects version %s as missing", (v) => {
    expect(bad(sanitizeLayout({ version: v, items: [rawItem()] }))).toBe("missing_version");
  });

  it("rejects a layout with no version", () => {
    expect(bad(sanitizeLayout({ items: [rawItem()] }))).toBe("missing_version");
  });

  it.each([[0], [-1], [2], [99]])("rejects version %s as unsupported", (v) => {
    expect(bad(sanitizeLayout(raw([rawItem()], v)))).toBe("unsupported_version");
  });

  it("calls an unknown version unsupported instead of guessing", () => {
    expect(bad(sanitizeLayout(raw([], 2)))).toBe("unsupported_version");
  });

  it("rejects non-objects and a missing items list", () => {
    for (const v of [null, 3, "x", [], undefined]) expect(bad(sanitizeLayout(v))).toBe("not_an_object");
    expect(bad(sanitizeLayout({ version: 1 }))).toBe("bad_items");
    expect(bad(sanitizeLayout({ version: 1, items: {} }))).toBe("bad_items");
  });

  it("runs each migration in order up to the target version", () => {
    const calls: number[] = [];
    const table: Migrations = {
      1: (r) => (calls.push(1), { ...r, a: true }),
      2: (r) => (calls.push(2), { ...r, b: true }),
    };
    expect(migrateLayout({ version: 1, items: [] }, table, 3)).toEqual({ ok: true, raw: { version: 3, items: [], a: true, b: true } });
    expect(calls).toEqual([1, 2]);
    expect(migrateLayout({ version: 2, items: [] }, table, 3)).toMatchObject({ ok: true, raw: { version: 3, b: true } });
  });

  it("errors when a migration step is missing or the layout is newer than the target", () => {
    expect(migrateLayout({ version: 1, items: [] }, {}, 2)).toMatchObject({ ok: false, error: { code: "unsupported_version" } });
    expect(migrateLayout({ version: 4, items: [] }, {}, 3)).toMatchObject({ ok: false, error: { code: "unsupported_version" } });
  });
});

describe("parseLayoutJson", () => {
  it("reports bad JSON and oversize input", () => {
    expect(bad(parseLayoutJson("{nope"))).toBe("not_json");
    expect(bad(parseLayoutJson(" ".repeat(300_000)))).toBe("too_large");
  });
  it("parses valid JSON", () => {
    expect(good(parseLayoutJson(JSON.stringify(raw([rawItem()])))).warnings).toEqual([]);
  });
});

describe("sanitize", () => {
  it("drops unknown widgets (and summary, which is not a grid widget)", () => {
    const r = good(sanitizeLayout(raw([rawItem({ id: "x", widgetId: "nope" }), rawItem({ id: "s", widgetId: "summary" }), rawItem()])));
    expect(r.layout.items.map((i) => i.id)).toEqual(["a"]);
    expect(r.warnings.map((w) => w.code)).toEqual(["unknown_widget", "unknown_widget"]);
  });

  it("drops items that are not objects, have bad ids or non-finite numbers, and duplicates", () => {
    const r = good(
      sanitizeLayout(
        raw([null, 5, rawItem({ id: "bad id!" }), rawItem({ id: 7 }), rawItem({ id: "n", x: "0" }), rawItem({ id: "i", w: Number.NaN }), rawItem(), rawItem({ y: 40 })]),
      ),
    );
    expect(r.layout.items.map((i) => i.id)).toEqual(["a"]);
    expect(r.warnings.map((w) => w.code)).toEqual([
      "item_not_an_object",
      "item_not_an_object",
      "bad_id",
      "bad_id",
      "bad_geometry",
      "bad_geometry",
      "duplicate_id",
    ]);
  });

  it("clamps sizes and positions to the widget's limits and 12 columns", () => {
    const r = good(sanitizeLayout(raw([rawItem({ w: 99, h: 99, x: 50, y: -5 }), rawItem({ id: "w", widgetId: "weather", sources: ["wx"], w: 0, h: 0, x: 0, y: 40 })])));
    expect(r.layout.items[0]).toMatchObject({ w: 12, h: 16, x: 0, y: 0 });
    expect(r.layout.items[1]).toMatchObject({ w: 2, h: 3 });
  });

  it("rounds fractional numbers", () => {
    expect(good(sanitizeLayout(raw([rawItem({ x: 1.4, y: 0.6, w: 4.2, h: 8.5 })]))).layout.items[0]).toMatchObject({ x: 1, y: 1, w: 4, h: 9 });
  });

  it("removes overlaps, keeping pinned items in place", () => {
    const r = good(sanitizeLayout(raw([rawItem({ id: "a" }), rawItem({ id: "p", pinned: true, widgetId: "events", sources: ["cal"] })])));
    expect(hasOverlap(r.layout.items)).toBe(false);
    expect(r.layout.items.find((i) => i.id === "p")).toMatchObject({ y: 0, pinned: true });
    expect(r.layout.items.find((i) => i.id === "a")?.y).toBe(8);
  });

  it("unpins a pinned item that overlaps an earlier pinned one", () => {
    const r = good(sanitizeLayout(raw([rawItem({ id: "p1", pinned: true }), rawItem({ id: "p2", pinned: true })])));
    expect(r.layout.items.map((i) => i.pinned)).toEqual([true, false]);
    expect(r.warnings.map((w) => w.code)).toContain("pinned_overlap");
  });

  it(`keeps at most ${String(MAX_ITEMS)} items`, () => {
    const many = Array.from({ length: MAX_ITEMS + 5 }, (_, n) => rawItem({ id: `i${String(n)}`, y: n * 16 }));
    const r = good(sanitizeLayout(raw(many)));
    expect(r.layout.items.length).toBeLessThanOrEqual(MAX_ITEMS);
    expect(r.warnings.some((w) => w.code === "too_many_items")).toBe(true);
  });

  it("does not let an extreme y survive", () => {
    const r = good(sanitizeLayout(raw([rawItem({ y: 1e12 })])));
    expect(r.layout.items[0]?.y).toBe(500);
  });
});

describe("kind rule in layouts", () => {
  it("keeps the kind of the first source and drops the rest for a non-needs_me widget", () => {
    const r = good(sanitizeLayout(raw([rawItem({ sources: ["canvas", "cal", "ls"] })])));
    expect(r.layout.items[0]?.sources).toEqual(["canvas", "ls"]);
    expect(r.warnings.map((w) => w.code)).toContain("sources_adjusted");
  });

  it("drops sources the widget does not allow", () => {
    expect(good(sanitizeLayout(raw([rawItem({ widgetId: "canvas", sources: ["ls", "canvas", "wx"] })]))).layout.items[0]?.sources).toEqual(["canvas"]);
  });

  it("falls back to the default sources when none survive", () => {
    expect(good(sanitizeLayout(raw([rawItem({ sources: ["wx"] })]))).layout.items[0]?.sources).toEqual(["canvas", "ls", "manual"]);
    expect(good(sanitizeLayout(raw([rawItem({ sources: "canvas" })]))).layout.items[0]?.sources).toEqual(["canvas", "ls", "manual"]);
  });

  it("lets needs_me hold several kinds but not weather", () => {
    const r = good(sanitizeLayout(raw([rawItem({ widgetId: "needs_me", sources: ["manual", "cal", "wx", "gmail"] })])));
    expect(r.layout.items[0]?.sources).toEqual(["cal", "gmail", "manual"]);
  });

  it("orders sources canonically and removes duplicates", () => {
    expect(good(sanitizeLayout(raw([rawItem({ sources: ["manual", "canvas", "manual"] })]))).layout.items[0]?.sources).toEqual(["canvas", "manual"]);
  });

  it("keeps a gmail+canvas tasks widget whatever the owed toggle says (validity does not depend on it)", () => {
    expect(good(sanitizeLayout(raw([rawItem({ sources: ["canvas", "gmail"] })]))).layout.items[0]?.sources).toEqual(["canvas", "gmail"]);
  });
});

describe("options", () => {
  it("keeps primitives and drops objects, unsafe keys and long strings", () => {
    const options = JSON.parse(
      '{"ok":1,"flag":true,"s":"x","o":{"a":1},"arr":[1],"n":null,"__proto__":{"polluted":true},"constructor":1}',
    ) as Record<string, unknown>;
    const r = good(sanitizeLayout(raw([rawItem({ options: { ...options, long: "y".repeat(500) } })])));
    expect(r.layout.items[0]?.options).toEqual({ ok: 1, flag: true, s: "x" });
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });
});

describe("round trip", () => {
  it.each(["main", "student", "work", "minimal"] as TemplateName[])("serialize then parse gives the %s template back", (name) => {
    const layout = buildTemplate(name);
    const r = good(parseLayoutJson(serializeLayout(layout)));
    expect(r.layout).toEqual(layout);
    expect(r.warnings).toEqual([]);
  });

  it("sanitize is idempotent and serialize is stable over random junk (fixed seed)", () => {
    const next = rng(2024);
    const widgets = ["tasks", "events", "weather", "week", "needs_me", "canvas", "ghost"];
    for (let round = 0; round < 60; round++) {
      const items = Array.from({ length: int(next, 0, 25) }, (_, n) =>
        rawItem({
          id: `r${String(n)}`,
          widgetId: widgets[int(next, 0, widgets.length - 1)],
          x: int(next, -5, 20),
          y: int(next, -5, 600),
          w: int(next, -2, 20),
          h: int(next, -2, 20),
          pinned: next() < 0.4,
          sources: ["cal", "canvas", "ls", "gmail", "wx", "manual", "zzz"].filter(() => next() < 0.4),
        }),
      );
      const once = good(sanitizeLayout(raw(items))).layout;
      expect(hasOverlap(once.items)).toBe(false);
      const twice = good(sanitizeLayout(JSON.parse(serializeLayout(once)))).layout;
      expect(twice).toEqual(once);
      expect(serializeLayout(twice)).toBe(serializeLayout(once));
    }
  });

  it("keeps layouts built with the editing helpers valid", () => {
    const l = layoutOf(item("a", "tasks", 0, 0, 4, 5), item("b", "events", 4, 0, 4, 5));
    expect(good(sanitizeLayout(JSON.parse(serializeLayout(l)))).layout).toEqual(l);
  });
});
