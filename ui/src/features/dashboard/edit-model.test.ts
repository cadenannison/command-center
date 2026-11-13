import { describe, expect, it } from "vitest";
import { DEFAULT_LAYOUTS, MAX_ITEMS, WIDGETS, getWidget, type Layout, type LayoutItem } from "../../layout";
import { item, layoutOf } from "../../layout/fixtures";
import { addBlocker, exportDocument, galleryEntries, nextItemId, presetState } from "./edit-model";
import { layoutToWire } from "./wire";

describe("galleryEntries", () => {
  it("has one row per registry widget, in registry order, with name, kind, a description and the default size", () => {
    const rows = galleryEntries();
    expect(rows.map((r) => r.widgetId)).toEqual(WIDGETS.map((w) => w.id));
    for (const row of rows) {
      const def = getWidget(row.widgetId);
      expect(row.name).toBe(def?.title);
      expect(row.kind).toBe(def?.kind);
      expect(row.description.length).toBeGreaterThan(10);
    }
  });

  it("gives each widget the size addWidget gives it: M clamped to the widget's limits", () => {
    const sizes = Object.fromEntries(galleryEntries().map((r) => [r.widgetId, r.size]));
    expect(sizes.events).toEqual({ w: 4, h: 8 });
    expect(sizes.weather).toEqual({ w: 4, h: 8 });
    expect(sizes.week).toEqual({ w: 4, h: 8 });
  });
});

describe("nextItemId", () => {
  it("starts at 1 and never reuses a number that is in use", () => {
    expect(nextItemId(layoutOf(), "events")).toBe("events-1");
    expect(nextItemId(layoutOf(item("events-1", "events", 0, 0, 4, 8)), "events")).toBe("events-2");
    expect(nextItemId(layoutOf(item("events-7", "events", 0, 0, 4, 8)), "events")).toBe("events-8");
  });

  it("does not mix widgets and is not fooled by another id that merely starts the same", () => {
    const layout = layoutOf(item("tasks-3", "tasks", 0, 0, 4, 8), item("my_tasks-1", "my_tasks", 4, 0, 4, 8));
    expect(nextItemId(layout, "tasks")).toBe("tasks-4");
    expect(nextItemId(layout, "my_tasks")).toBe("my_tasks-2");
  });
});

describe("addBlocker", () => {
  it("allows a second copy of a widget (the registry has no one-per-dashboard rule)", () => {
    expect(addBlocker(DEFAULT_LAYOUTS.minimal, "events")).toBeNull();
  });

  it("refuses at the item limit and when there is no room below, and an unknown widget", () => {
    const full: Layout = layoutOf(
      ...Array.from({ length: MAX_ITEMS }, (_, n): LayoutItem => item(`events-${String(n + 1)}`, "events", 0, n * 5, 3, 5)),
    );
    expect(addBlocker(full, "events")).toMatch(/at most 50 widgets/);
    expect(addBlocker(layoutOf(item("events-1", "events", 0, 495, 4, 5)), "events")).toMatch(/no room/);
    expect(addBlocker(DEFAULT_LAYOUTS.main, "nope")).toMatch(/not available/);
  });
});

describe("presetState", () => {
  const eventsItem = item("events-1", "events", 0, 0, 5, 10);

  it("allows a preset that fits and differs from the current size", () => {
    expect(presetState(eventsItem, "S")).toMatchObject({ disabled: false, reason: null, size: { w: 3, h: 5 } });
    expect(presetState(eventsItem, "L")).toMatchObject({ disabled: false, size: { w: 7, h: 10 } });
  });

  it("disables a preset that is outside the widget's min and max and says the limits", () => {
    const state = presetState(item("weather-1", "weather", 0, 0, 3, 6), "L");
    expect(state.disabled).toBe(true);
    expect(state.reason).toBe("Weather is limited to 2×3 up to 6×9.");
  });

  it("disables the size the widget already has", () => {
    expect(presetState(item("events-1", "events", 0, 0, 4, 8), "M")).toMatchObject({ disabled: true, reason: "Already this size." });
  });

  it("disables every preset on a pinned widget", () => {
    const pinned = item("events-1", "events", 0, 0, 5, 10, true);
    for (const name of ["S", "M", "L"] as const) expect(presetState(pinned, name).reason).toBe("Unpin it to resize.");
  });
});

describe("exportDocument", () => {
  it("is exactly the stored v1 document, nothing else", () => {
    const { content } = exportDocument("Main", DEFAULT_LAYOUTS.main);
    expect(JSON.parse(content)).toEqual(layoutToWire(DEFAULT_LAYOUTS.main));
    expect(Object.keys(JSON.parse(content) as object)).toEqual(["version", "items"]);
    expect(content.endsWith("\n")).toBe(true);
  });

  it("names the file command-center-<dashboard name>-layout.json", () => {
    expect(exportDocument("Main", DEFAULT_LAYOUTS.main).filename).toBe("command-center-Main-layout.json");
    expect(exportDocument("School year 2026", DEFAULT_LAYOUTS.main).filename).toBe("command-center-School-year-2026-layout.json");
  });

  it("keeps a path or shell character out of the file name and falls back when nothing is left", () => {
    expect(exportDocument("../etc/passwd", DEFAULT_LAYOUTS.main).filename).toBe("command-center-etc-passwd-layout.json");
    expect(exportDocument('a:b*c?"d<e>|f', DEFAULT_LAYOUTS.main).filename).toBe("command-center-a-b-c-d-e-f-layout.json");
    expect(exportDocument("///", DEFAULT_LAYOUTS.main).filename).toBe("command-center-dashboard-layout.json");
    expect(exportDocument("Écoles ☃", DEFAULT_LAYOUTS.main).filename).toBe("command-center-Écoles-layout.json");
  });

  it("caps a very long name", () => {
    expect(exportDocument("x".repeat(500), DEFAULT_LAYOUTS.main).filename.length).toBeLessThan(100);
  });
});
