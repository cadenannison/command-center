import { describe, expect, it } from "vitest";
import { addWidget, move } from "./grid";
import { canRedo, canUndo, HISTORY_LIMIT, historyReducer, initHistory, type HistoryAction, type HistoryState } from "./history";
import { item, layoutOf } from "./fixtures";
import { DEFAULT_LAYOUTS } from "./defaults";

const run = (state: HistoryState, ...actions: HistoryAction[]) => actions.reduce(historyReducer, state);
const base = layoutOf(item("a", "tasks", 0, 0, 4, 5));
const edited = move(base, "a", 4, 0, 12);
const edited2 = addWidget(edited, "events", "b", 12);

describe("history", () => {
  it("starts with nothing to undo or redo", () => {
    const s = initHistory(base);
    expect([canUndo(s), canRedo(s)]).toEqual([false, false]);
  });

  it("undo and redo round trip through several edits", () => {
    const s = run(initHistory(base), { type: "apply", layout: edited }, { type: "apply", layout: edited2 });
    expect(s.present).toBe(edited2);
    const undone = run(s, { type: "undo" }, { type: "undo" });
    expect(undone.present).toBe(base);
    expect(canUndo(undone)).toBe(false);
    const redone = run(undone, { type: "redo" }, { type: "redo" });
    expect(redone.present).toBe(edited2);
    expect(redone).toEqual(s);
  });

  it("clears redo when a new change is applied after an undo", () => {
    const s = run(initHistory(base), { type: "apply", layout: edited }, { type: "undo" }, { type: "apply", layout: edited2 });
    expect(s.future).toEqual([]);
    expect(s.present).toBe(edited2);
    expect(run(s, { type: "redo" })).toBe(s);
  });

  it("ignores undo and redo when there is nothing to do", () => {
    const s = initHistory(base);
    expect(historyReducer(s, { type: "undo" })).toBe(s);
    expect(historyReducer(s, { type: "redo" })).toBe(s);
  });

  it("does not record a change that equals the present", () => {
    const s = initHistory(base);
    expect(historyReducer(s, { type: "apply", layout: base })).toBe(s);
    expect(historyReducer(s, { type: "apply", layout: structuredClone(base) })).toBe(s);
  });

  it("reset returns to the default and can be undone", () => {
    const s = run(initHistory(edited2, DEFAULT_LAYOUTS.main), { type: "reset" });
    expect(s.present).toBe(DEFAULT_LAYOUTS.main);
    expect(run(s, { type: "undo" }).present).toBe(edited2);
    expect(run(s, { type: "undo" }, { type: "redo" }).present).toBe(DEFAULT_LAYOUTS.main);
  });

  it("reset on the default itself records nothing", () => {
    const s = initHistory(DEFAULT_LAYOUTS.main);
    expect(historyReducer(s, { type: "reset" })).toBe(s);
  });

  it("keeps at most the history limit", () => {
    let s = initHistory(layoutOf());
    for (let n = 0; n < HISTORY_LIMIT + 20; n++) {
      s = historyReducer(s, { type: "apply", layout: addWidget(s.present, "weather", `w${String(n)}`, 12) });
    }
    expect(s.past).toHaveLength(HISTORY_LIMIT);
    expect(s.present.items).toHaveLength(HISTORY_LIMIT + 20);
  });
});
