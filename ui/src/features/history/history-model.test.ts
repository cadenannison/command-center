import { describe, expect, it } from "vitest";
import { buildDays, dayHeading, historyRange, HISTORY_DAYS, matches } from "./history-model";
import { at, entry, NOW } from "./history-test-support";
import type { HistoryDay } from "./use-history";

const days: HistoryDay[] = [
  {
    day: "2026-11-10",
    done_by_you: [entry("old", "done_by_you", at(10, 9))],
    gone: [entry("vanished", "gone", at(10, 12))],
  },
  {
    day: "2026-11-12",
    done_by_you: [entry("mine", "done_by_you", at(12, 9), { title: "Lab report" })],
    done_by_source: [entry("theirs", "done_by_source", at(12, 11), { title: "Quiz" })],
    dismissed: [entry("noise", "dismissed", at(12, 13), { title: "Newsletter", note: "no reply needed" })],
  },
];

describe("historyRange", () => {
  it("asks for the last 30 local days up to and including today", () => {
    expect(HISTORY_DAYS).toBe(30);
    expect(historyRange(NOW)).toEqual({ from: "2026-10-14", to: "2026-11-12" });
  });
});

describe("dayHeading", () => {
  it("reads the key as a local date", () => {
    expect(dayHeading("2026-11-12")).toBe("Thursday, Nov 12");
    expect(dayHeading("2026-01-01")).toBe("Thursday, Jan 1");
  });
});

describe("buildDays", () => {
  it("orders days newest first and entries newest first, with whole-day counts", () => {
    const views = buildDays(days, "all", "", "2026-11-12");
    expect(views.map((v) => v.day)).toEqual(["2026-11-12", "2026-11-10"]);
    expect(views[0]?.rows.map((r) => r.entry.item_id)).toEqual(["noise", "theirs", "mine"]);
    expect(views[0]).toMatchObject({ done: 2, dismissed: 1 });
    expect(views[1]).toMatchObject({ done: 1, dismissed: 0 });
  });

  it("filters by outcome and drops a day with nothing left", () => {
    const dismissed = buildDays(days, "dismissed", "", "2026-11-12");
    expect(dismissed.map((v) => v.day)).toEqual(["2026-11-12"]);
    expect(dismissed[0]?.rows.map((r) => r.entry.item_id)).toEqual(["noise"]);
    const done = buildDays(days, "done", "", "2026-11-12");
    expect(done.flatMap((v) => v.rows.map((r) => r.entry.item_id))).toEqual(["theirs", "mine", "old"]);
  });

  it("keeps outcome gone under All only", () => {
    expect(buildDays(days, "all", "", "2026-11-12").flatMap((v) => v.rows.map((r) => r.entry.outcome))).toContain("gone");
    for (const filter of ["done", "dismissed"] as const) {
      expect(buildDays(days, filter, "", "2026-11-12").flatMap((v) => v.rows.map((r) => r.entry.outcome))).not.toContain("gone");
    }
  });

  it("searches titles and notes, ignoring case and outer spaces", () => {
    const ids = (q: string) => buildDays(days, "all", q, "2026-11-12").flatMap((v) => v.rows.map((r) => r.entry.item_id));
    expect(ids("  LAB ")).toEqual(["mine"]);
    expect(ids("no reply")).toEqual(["noise"]);
    expect(ids("zzz")).toEqual([]);
  });

  it("offers Restore only on today's own check-offs and dismissals", () => {
    const rows = buildDays(days, "all", "", "2026-11-12").flatMap((v) => v.rows);
    const restorable = rows.filter((r) => r.restorable).map((r) => r.entry.item_id);
    // Today: mine (done_by_you) and noise (dismissed). Not theirs (the source finished it), not an older day, not gone.
    expect(restorable.sort()).toEqual(["mine", "noise"]);
  });

  it("tolerates a day with missing lists", () => {
    expect(buildDays([{ day: "2026-11-12" }], "all", "", "2026-11-12")).toEqual([]);
  });
});

describe("matches", () => {
  it("treats a note that is null as empty", () => {
    expect(matches(entry("x", "done_by_you", at(12, 9), { note: null }), "all", "x")).toBe(true);
    expect(matches(entry("x", "done_by_you", at(12, 9), { note: null, title: "abc" }), "all", "note")).toBe(false);
  });
});
