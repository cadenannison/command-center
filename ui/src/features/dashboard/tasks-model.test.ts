import { describe, expect, it } from "vitest";
import {
  deriveTasksState,
  formatClock,
  formatDue,
  formatPoints,
  groupOf,
  groupTasks,
  limitRows,
  rowLimit,
  safeHref,
  sourceIdOf,
  topReason,
  type TaskItem,
} from "./tasks-model";

// A local-time clock: Thu Nov 12 2026, 10:00 AM. Dates are built in local time so the tests hold in any zone.
const NOW = new Date(2026, 10, 12, 10, 0, 0).getTime();
const HOUR = 3_600_000;
const at = (offsetMs: number) => new Date(NOW + offsetMs).toISOString();

const task = (id: string, due: string | null, extra: Partial<TaskItem> = {}): TaskItem => ({
  id,
  title: `Task ${id}`,
  source: "canvas",
  due,
  link: null,
  done: false,
  priority: 5,
  reasons: [],
  ...extra,
});

describe("groupOf", () => {
  it("is overdue one millisecond past, and not overdue exactly now", () => {
    expect(groupOf(NOW - 1, NOW)).toBe("overdue");
    expect(groupOf(NOW, NOW)).toBe("next48");
  });
  it("puts exactly 48 hours in the next 48 hours and one millisecond later in Later", () => {
    expect(groupOf(NOW + 48 * HOUR, NOW)).toBe("next48");
    expect(groupOf(NOW + 48 * HOUR + 1, NOW)).toBe("later");
  });
  it("puts no due time in No due date", () => {
    expect(groupOf(null, NOW)).toBe("undated");
  });
});

describe("groupTasks", () => {
  it("groups in order, keeps the server order inside a group and puts No due date last", () => {
    const groups = groupTasks(
      [
        task("u1", null),
        task("l1", at(72 * HOUR)),
        task("n1", at(HOUR)),
        task("o1", at(-HOUR)),
        task("n2", at(2 * HOUR)),
        task("o2", at(-5 * HOUR)),
      ],
      NOW,
    );
    expect(groups.map((g) => g.label)).toEqual(["Overdue", "Due in the next 48 hours", "Later", "No due date"]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([["o1", "o2"], ["n1", "n2"], ["l1"], ["u1"]]);
  });
  it("hides done items and leaves out empty groups", () => {
    const groups = groupTasks([task("d", at(HOUR), { done: true }), task("u", null)], NOW);
    expect(groups.map((g) => g.id)).toEqual(["undated"]);
  });
  it("labels undated items even when they are the only ones", () => {
    expect(groupTasks([task("u", null)], NOW)[0]?.label).toBe("No due date");
  });
  it("treats an unreadable due as undated", () => {
    expect(groupTasks([task("x", "not a date")], NOW)[0]?.id).toBe("undated");
  });
});

describe("limitRows", () => {
  const groups = groupTasks([task("a", at(-HOUR)), task("b", at(HOUR)), task("c", at(2 * HOUR)), task("d", null)], NOW);
  it("keeps the first rows across groups and counts the rest", () => {
    const { groups: kept, more } = limitRows(groups, 3);
    expect(kept.flatMap((g) => g.items.map((i) => i.id))).toEqual(["a", "b", "c"]);
    expect(more).toBe(1);
  });
  it("drops a group left with no rows", () => {
    expect(limitRows(groups, 1).groups.map((g) => g.id)).toEqual(["overdue"]);
  });
  it("shows everything with no limit", () => {
    expect(limitRows(groups, rowLimit(3)).more).toBe(0);
  });
  it("uses 3, 6 and all rows for the height tiers", () => {
    expect([rowLimit(1), rowLimit(2), rowLimit(3)]).toEqual([3, 6, Number.POSITIVE_INFINITY]);
  });
});

describe("12-hour formatting", () => {
  it("prints midnight and noon as 12", () => {
    expect(formatClock(new Date(2026, 10, 12, 0, 5))).toBe("12:05 AM");
    expect(formatClock(new Date(2026, 10, 12, 12, 0))).toBe("12:00 PM");
  });
  it("prints afternoon hours without a 24-hour value", () => {
    expect(formatClock(new Date(2026, 10, 12, 15, 5))).toBe("3:05 PM");
    expect(formatClock(new Date(2026, 10, 12, 23, 59))).toBe("11:59 PM");
  });
  it("names the day relative to now", () => {
    const local = (d: number, h: number) => new Date(2026, 10, d, h, 0).toISOString();
    expect(formatDue(local(12, 15), NOW)).toBe("Today 3:00 PM");
    expect(formatDue(local(13, 9), NOW)).toBe("Tomorrow 9:00 AM");
    expect(formatDue(local(11, 18), NOW)).toBe("Yesterday 6:00 PM");
    expect(formatDue(local(15, 16), NOW)).toBe("Sun 4:00 PM");
    expect(formatDue(local(25, 16), NOW)).toBe("Nov 25, 4:00 PM");
  });
  it("is empty without a readable due", () => {
    expect(formatDue(null, NOW)).toBe("");
    expect(formatDue("nope", NOW)).toBe("");
  });
});

describe("safeHref", () => {
  it("accepts http and https", () => {
    expect(safeHref("https://canvas.example.edu/courses/1")).toBe("https://canvas.example.edu/courses/1");
    expect(safeHref("http://example.com/a")).toBe("http://example.com/a");
  });
  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>1</script>",
    "file:///etc/passwd",
    "vbscript:x",
    "//example.com/path",
    "/relative/path",
    "",
  ])("rejects %j", (link) => {
    expect(safeHref(link)).toBeNull();
  });
  it("rejects a missing link", () => {
    expect(safeHref(null)).toBeNull();
  });
});

describe("reasons and sources", () => {
  it("picks the reason with the most points, the first of equals", () => {
    const r = [
      { code: "a", text: "A", points: 2 },
      { code: "b", text: "B", points: 5 },
      { code: "c", text: "C", points: 5 },
    ];
    expect(topReason(r)?.code).toBe("b");
    expect(topReason([])).toBeNull();
  });
  it("prints points with a sign", () => {
    expect([formatPoints(3), formatPoints(0), formatPoints(-2)]).toEqual(["+3", "0", "−2"]);
  });
  it("maps unknown sources to My tasks", () => {
    expect(sourceIdOf("canvas")).toBe("canvas");
    expect(sourceIdOf("local")).toBe("manual");
  });
});

describe("deriveTasksState", () => {
  const base = { data: undefined, isPending: true, isError: false, dataUpdatedAt: 0 };
  it("is loading, then error, with no data", () => {
    expect(deriveTasksState(base).kind).toBe("loading");
    expect(deriveTasksState({ ...base, isPending: false, isError: true })).toEqual({ kind: "error" });
  });
  it("is empty when every item is done or there are none", () => {
    expect(deriveTasksState({ ...base, isPending: false, data: [] }).kind).toBe("empty");
    expect(deriveTasksState({ ...base, isPending: false, data: [task("a", null, { done: true })] }).kind).toBe("empty");
  });
  it("is stale, with a 12-hour time, when a refresh failed but data exists", () => {
    const state = deriveTasksState({
      ...base,
      isPending: false,
      isError: true,
      data: [task("a", null)],
      dataUpdatedAt: new Date(2026, 10, 12, 14, 7).getTime(),
    });
    expect(state).toEqual({ kind: "stale", lastSynced: "2:07 PM" });
  });
  it("is ready with open items", () => {
    expect(deriveTasksState({ ...base, isPending: false, data: [task("a", null)] }).kind).toBe("ready");
  });
});
