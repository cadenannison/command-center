import { describe, expect, it } from "vitest";
import { buildAgenda, isAllDay, limitAgenda, type EventRow } from "./events-model";

const at = (d: number, h = 0, min = 0) => new Date(2026, 10, d, h, min).getTime();
const NOW = at(12, 15, 30);
const row = (id: string, startMs: number, endMs: number | null = null): EventRow => ({
  id, title: id, startMs, endMs, allDay: isAllDay(startMs, endMs), source: "cal", location: null, href: null,
});
const shown = (rows: EventRow[], h: 1 | 2 | 3) =>
  limitAgenda(buildAgenda(rows, NOW, h === 3), h).days.flatMap((d) => d.rows.map((r) => r.event.id));

describe("height tier 1 is now and next", () => {
  const rows = [row("all", at(12), at(13)), row("now", at(12, 15), at(12, 16)), row("next", at(12, 17), at(12, 18)), row("later", at(12, 19), at(12, 20))];

  it("shows the Now and Next rows even when an all-day event sorts first", () => {
    expect(shown(rows, 1)).toEqual(["now", "next"]);
    expect(limitAgenda(buildAgenda(rows, NOW, false), 1).more).toBe(2);
  });

  it("fills with the other rows, in order, when there is no Now or no Next", () => {
    expect(shown([row("all", at(12), at(13)), row("later", at(12, 19), at(12, 20))], 1)).toEqual(["all", "later"]);
    expect(shown([row("all", at(12), at(13)), row("a", at(12, 19)), row("b", at(12, 20))], 1)).toEqual(["all", "a"]);
  });

  it("H2 still lists in day order, all-day first", () => {
    expect(shown(rows, 2)).toEqual(["all", "now", "next", "later"]);
  });
});

describe("a multi-day event in progress", () => {
  const trip = row("trip", at(11, 20), at(14, 10));
  it("is Now only on today's row, and continues on later days unmarked", () => {
    const agenda = buildAgenda([trip], NOW, false);
    expect(agenda.days.map((d) => [d.label, d.rows[0]?.marker, d.rows[0]?.continues])).toEqual([
      ["Today", "now", true],
      ["Tomorrow", null, true],
      ["Sat, Nov 14", null, true],
    ]);
  });
});
