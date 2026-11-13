import { describe, expect, it } from "vitest";
import {
  countText,
  dayPrefix,
  isOverdue,
  kindLabel,
  limitRows,
  needsMeRows,
  rowLimit,
  rowSource,
  whenLabel,
  type NeedsMeItem,
} from "./needs-me-model";

// vitest.config.ts pins TZ to America/Denver (test-zone.test.ts proves it). Thursday, Nov 12, 2026, 3:30 PM.
const NOW = new Date(2026, 10, 12, 15, 30).getTime();
const at = (m: number, d: number, h: number, min = 0) => new Date(2026, m, d, h, min).toISOString();

const item = (id: string, extra: Partial<NeedsMeItem> = {}): NeedsMeItem => ({
  id,
  kind: "task",
  title: `Item ${id}`,
  source: "canvas",
  at: at(10, 12, 17),
  link: null,
  priority: 7,
  reasons: [],
  ...extra,
});

describe("kindLabel and needsMeRows", () => {
  it("names the four kinds and has no label for weather", () => {
    expect(kindLabel("task")).toBe("Task");
    expect(kindLabel("assignment")).toBe("Assignment");
    expect(kindLabel("email")).toBe("Reply");
    expect(kindLabel("event")).toBe("Event");
    expect(kindLabel("weather")).toBeNull();
  });

  it("keeps the server's order and drops weather", () => {
    const rows = needsMeRows([item("b", { priority: 3 }), item("w", { kind: "weather" }), item("a", { priority: 9 })]);
    expect(rows.map((r) => r.id)).toEqual(["b", "a"]);
  });
});

describe("whenLabel", () => {
  it("is 'Starts 2:30 PM' for an event later today and 'Now' once it has started", () => {
    expect(whenLabel({ kind: "event", at: at(10, 12, 17, 30) }, NOW)).toBe("Starts 5:30 PM");
    expect(whenLabel({ kind: "event", at: at(10, 12, 14, 30) }, NOW)).toBe("Now");
    expect(whenLabel({ kind: "event", at: new Date(NOW).toISOString() }, NOW)).toBe("Now");
    expect(whenLabel({ kind: "event", at: new Date(NOW + 1).toISOString() }, NOW)).toMatch(/^Starts 3:30 PM$/);
  });

  it("is 'Due 5:00 PM' ahead and 'Overdue' once the time has passed, for a task, assignment and reply alike", () => {
    for (const kind of ["task", "assignment", "email"] as const) {
      expect(whenLabel({ kind, at: at(10, 12, 17) }, NOW)).toBe("Due 5:00 PM");
      expect(whenLabel({ kind, at: at(10, 12, 9) }, NOW)).toBe("Overdue");
    }
  });

  it("treats due exactly now as not yet overdue, and one millisecond earlier as overdue", () => {
    expect(whenLabel({ kind: "task", at: new Date(NOW).toISOString() }, NOW)).toBe("Due 3:30 PM");
    expect(whenLabel({ kind: "task", at: new Date(NOW - 1).toISOString() }, NOW)).toBe("Overdue");
    expect(isOverdue({ kind: "task", at: new Date(NOW - 1).toISOString() }, NOW)).toBe(true);
    expect(isOverdue({ kind: "event", at: new Date(NOW - 1).toISOString() }, NOW)).toBe(false);
  });

  it("uses 12-hour times, with 12:00 AM and 12:00 PM", () => {
    expect(whenLabel({ kind: "task", at: at(10, 13, 0) }, NOW)).toBe("Due Tomorrow 12:00 AM");
    expect(whenLabel({ kind: "task", at: at(10, 12, 23, 59) }, NOW)).toBe("Due 11:59 PM");
    expect(whenLabel({ kind: "event", at: at(10, 13, 12) }, NOW)).toBe("Starts Tomorrow 12:00 PM");
  });

  it("adds Tomorrow across the local midnight, whatever the hour", () => {
    expect(whenLabel({ kind: "task", at: at(10, 12, 23, 59) }, NOW)).toBe("Due 11:59 PM");
    expect(whenLabel({ kind: "task", at: at(10, 13, 0, 1) }, NOW)).toBe("Due Tomorrow 12:01 AM");
    const lateNow = new Date(2026, 10, 12, 23, 59).getTime();
    expect(whenLabel({ kind: "event", at: at(10, 13, 0, 30) }, lateNow)).toBe("Starts Tomorrow 12:30 AM");
  });

  it("names a weekday within the next week and a date after that", () => {
    expect(whenLabel({ kind: "task", at: at(10, 16, 9) }, NOW)).toBe("Due Mon 9:00 AM");
    expect(whenLabel({ kind: "task", at: at(10, 19, 9) }, NOW)).toBe("Due Nov 19 9:00 AM");
  });

  it("is empty for no or unreadable time", () => {
    expect(whenLabel({ kind: "task", at: null }, NOW)).toBe("");
    expect(whenLabel({ kind: "event", at: "not a date" }, NOW)).toBe("");
  });
});

describe("dayPrefix across DST", () => {
  it("keeps the day count on the 25 hour day when clocks fall back (Sun Nov 1, 2026)", () => {
    const saturdayNoon = new Date(2026, 9, 31, 12).getTime();
    expect(dayPrefix(new Date(2026, 10, 1, 0, 30).getTime(), saturdayNoon)).toBe("Tomorrow");
    expect(dayPrefix(new Date(2026, 10, 1, 23, 30).getTime(), saturdayNoon)).toBe("Tomorrow");
    expect(dayPrefix(new Date(2026, 10, 2, 0, 30).getTime(), saturdayNoon)).toBe("Mon");
    // 24 hours after Saturday noon is still Sunday, 11 AM local, because that Sunday has 25 hours.
    expect(dayPrefix(saturdayNoon + 24 * 3_600_000, saturdayNoon)).toBe("Tomorrow");
  });

  it("keeps the day count on the 23 hour day when clocks spring forward (Sun Mar 8, 2026)", () => {
    const saturdayNoon = new Date(2026, 2, 7, 12).getTime();
    expect(dayPrefix(new Date(2026, 2, 8, 23, 30).getTime(), saturdayNoon)).toBe("Tomorrow");
    expect(dayPrefix(new Date(2026, 2, 9, 0, 30).getTime(), saturdayNoon)).toBe("Mon");
    // 24 hours after Saturday noon is already Sunday 1 PM; 36 hours is Monday 0:00.
    expect(dayPrefix(saturdayNoon + 36 * 3_600_000, saturdayNoon)).toBe("Mon");
  });

  it("labels an event on the fall-back day from the local clock, not elapsed hours", () => {
    const saturdayNoon = new Date(2026, 9, 31, 12).getTime();
    expect(whenLabel({ kind: "event", at: new Date(2026, 10, 1, 9).toISOString() }, saturdayNoon)).toBe("Starts Tomorrow 9:00 AM");
  });
});

describe("rows, counts and sources", () => {
  it("shows 3 rows at height 1, 6 at height 2 and all at height 3", () => {
    expect(rowLimit(1)).toBe(3);
    expect(rowLimit(2)).toBe(6);
    expect(rowLimit(3)).toBe(Number.POSITIVE_INFINITY);
  });

  it("limitRows keeps the first rows in order and counts the rest", () => {
    const rows = ["a", "b", "c", "d"];
    expect(limitRows(rows, 3)).toEqual({ shown: ["a", "b", "c"], more: 1 });
    expect(limitRows(rows, Number.POSITIVE_INFINITY)).toEqual({ shown: rows, more: 0 });
    expect(limitRows([], 3)).toEqual({ shown: [], more: 0 });
  });

  it("countText is singular for one", () => {
    expect(countText(1)).toBe("1 needs you");
    expect(countText(0)).toBe("0 need you");
    expect(countText(4)).toBe("4 need you");
  });

  it("maps sources to the design's sources; an event is Calendar and the unknown is My tasks", () => {
    expect(rowSource({ source: "canvas", kind: "assignment" })).toBe("canvas");
    expect(rowSource({ source: "gmail", kind: "email" })).toBe("gmail");
    expect(rowSource({ source: "apple_calendar", kind: "event" })).toBe("cal");
    expect(rowSource({ source: "local", kind: "task" })).toBe("manual");
  });
});
