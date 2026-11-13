import { describe, expect, it } from "vitest";
import {
  AGENDA_DAYS,
  agendaLabel,
  buildAgenda,
  eventRowsOf,
  eventsWindow,
  isAllDay,
  limitAgenda,
  rowLimit,
  showsDetail,
  showsMarkers,
  showsPast,
  timeText,
  untilText,
  type EventRow,
} from "./events-model";
import type { ApiEvent } from "./use-events";

const at = (y: number, m: number, d: number, h = 0, min = 0) => new Date(y, m - 1, d, h, min).getTime();
// Thursday, Nov 12, 2026, 3:30 PM Denver.
const NOW = at(2026, 11, 12, 15, 30);

const row = (id: string, startMs: number, endMs: number | null = null, extra: Partial<EventRow> = {}): EventRow => ({
  id,
  title: `Event ${id}`,
  startMs,
  endMs,
  allDay: isAllDay(startMs, endMs),
  source: "cal",
  location: null,
  href: null,
  ...extra,
});

const api = (id: string, start: string | null, extra: Partial<ApiEvent> = {}): ApiEvent => ({
  id,
  kind: "event",
  source: "apple_calendar",
  title: `Event ${id}`,
  start,
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: "2026-11-12T10:00:00Z",
  has_note: false,
  user_id: "local",
  ...extra,
});

const ids = (rows: readonly { event: EventRow }[]) => rows.map((r) => r.event.id);

describe("eventsWindow", () => {
  it("is today's local midnight to seven local midnights later", () => {
    const w = eventsWindow(NOW);
    expect(new Date(w.from).getTime()).toBe(at(2026, 11, 12));
    expect(new Date(w.to).getTime()).toBe(at(2026, 11, 19));
    expect(AGENDA_DAYS).toBe(7);
  });

  it("stays on local midnights across a DST change (a 25 hour day)", () => {
    const w = eventsWindow(at(2026, 10, 30, 12)); // the week of Nov 1, fall back
    expect(new Date(w.to).getTime()).toBe(at(2026, 11, 6));
    expect(new Date(w.to).getTime() - new Date(w.from).getTime()).toBe(7 * 24 * 3_600_000 + 3_600_000);
  });
});

describe("isAllDay", () => {
  it("is true from one local midnight to a later one, including a 25 hour day", () => {
    expect(isAllDay(at(2026, 11, 12), at(2026, 11, 13))).toBe(true);
    expect(isAllDay(at(2026, 11, 1), at(2026, 11, 2))).toBe(true);
    expect(isAllDay(at(2026, 3, 8), at(2026, 3, 9))).toBe(true); // a 23 hour day
    expect(isAllDay(at(2026, 11, 12), at(2026, 11, 15))).toBe(true);
  });
  it("is false for timed events, even one that starts at midnight", () => {
    expect(isAllDay(at(2026, 11, 12), at(2026, 11, 12, 3))).toBe(false);
    expect(isAllDay(at(2026, 11, 12, 9), at(2026, 11, 13))).toBe(false);
    expect(isAllDay(at(2026, 11, 12), null)).toBe(false);
  });
});

describe("eventRowsOf", () => {
  it("keeps calendar events only", () => {
    const rows = eventRowsOf([
      api("e", new Date(at(2026, 11, 12, 9)).toISOString()),
      api("w", new Date(at(2026, 11, 12)).toISOString(), { kind: "weather" }),
      api("a", new Date(at(2026, 11, 12, 9)).toISOString(), { kind: "assignment" }),
      api("t", new Date(at(2026, 11, 12, 9)).toISOString(), { kind: "task" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["e"]);
  });

  it("drops cancelled events and ones without a readable start", () => {
    const s = new Date(at(2026, 11, 12, 9)).toISOString();
    expect(eventRowsOf([api("c", s, { status: "cancelled" }), api("n", null), api("x", "garbage"), api("ok", s)]).map((r) => r.id)).toEqual(["ok"]);
  });

  it("reads location from raw.location, trimmed, and ignores anything else", () => {
    const s = new Date(at(2026, 11, 12, 9)).toISOString();
    const rows = eventRowsOf([
      api("a", s, { raw: { location: "  Room 4 " } }),
      api("b", s, { raw: { location: "   " } }),
      api("c", s, { raw: { location: 12 } }),
      api("d", s),
    ]);
    expect(rows.map((r) => r.location)).toEqual(["Room 4", null, null, null]);
  });

  it("keeps only http and https links", () => {
    const s = new Date(at(2026, 11, 12, 9)).toISOString();
    const rows = eventRowsOf([
      api("a", s, { link: "https://cal.example/e/1" }),
      api("b", s, { link: "http://cal.example/e/2" }),
      api("c", s, { link: "javascript:alert(1)" }),
      api("d", s, { link: "data:text/html,x" }),
      api("e", s, { link: null }),
      api("f", s),
    ]);
    expect(rows.map((r) => r.href)).toEqual(["https://cal.example/e/1", "http://cal.example/e/2", null, null, null, null]);
  });

  it("treats an end at or before the start as no end", () => {
    const s = new Date(at(2026, 11, 12, 9)).toISOString();
    expect(eventRowsOf([api("a", s, { end: s })])[0]?.endMs).toBeNull();
  });

  it("marks date-only events all day", () => {
    const rows = eventRowsOf([api("a", new Date(at(2026, 11, 12)).toISOString(), { end: new Date(at(2026, 11, 13)).toISOString() })]);
    expect(rows[0]?.allDay).toBe(true);
  });
});

describe("buildAgenda: grouping and order", () => {
  it("groups Today, Tomorrow, then dates, and skips empty days", () => {
    const agenda = buildAgenda(
      [row("t", at(2026, 11, 12, 17), at(2026, 11, 12, 18)), row("m", at(2026, 11, 13, 9)), row("f", at(2026, 11, 16, 9))],
      NOW,
      false,
    );
    expect(agenda.days.map((d) => d.label)).toEqual(["Today", "Tomorrow", "Mon, Nov 16"]);
    expect(agenda.days.map((d) => d.offset)).toEqual([0, 1, 4]);
    expect(agenda.total).toBe(3);
  });

  it("lists all-day events first, then timed events by start", () => {
    const agenda = buildAgenda(
      [row("late", at(2026, 11, 12, 20), at(2026, 11, 12, 21)), row("early", at(2026, 11, 12, 16)), row("all", at(2026, 11, 12), at(2026, 11, 13))],
      NOW,
      false,
    );
    expect(ids(agenda.days[0]?.rows ?? [])).toEqual(["all", "early", "late"]);
  });

  it("breaks ties by id so the order is stable", () => {
    const agenda = buildAgenda([row("b", at(2026, 11, 12, 16)), row("a", at(2026, 11, 12, 16))], NOW, false);
    expect(ids(agenda.days[0]?.rows ?? [])).toEqual(["a", "b"]);
  });

  it("leaves out events past the window", () => {
    expect(buildAgenda([row("far", at(2026, 11, 19, 9))], NOW, false).total).toBe(0);
  });
});

describe("buildAgenda: day boundaries", () => {
  it("puts 11:59 PM in Today and 12:00 AM in Tomorrow", () => {
    const agenda = buildAgenda([row("a", at(2026, 11, 12, 23, 59)), row("b", at(2026, 11, 13, 0, 0))], NOW, false);
    expect(agenda.days.map((d) => [d.label, ids(d.rows)])).toEqual([
      ["Today", ["a"]],
      ["Tomorrow", ["b"]],
    ]);
  });

  it("does not carry an event that ends exactly at midnight into the next day", () => {
    const agenda = buildAgenda([row("a", at(2026, 11, 12, 22), at(2026, 11, 13))], NOW, false);
    expect(agenda.days.map((d) => d.label)).toEqual(["Today"]);
  });

  it("shows a multi-day event on each day it overlaps, as continuing after the first", () => {
    const agenda = buildAgenda([row("trip", at(2026, 11, 12, 20), at(2026, 11, 13, 10))], NOW, false);
    expect(agenda.days.map((d) => d.rows[0]?.continues)).toEqual([false, true]);
    expect(timeText(agenda.days[1]?.rows[0] ?? fail())).toBe("Continues");
  });

  it("lists a multi-day all-day event under each day", () => {
    const agenda = buildAgenda([row("conf", at(2026, 11, 12), at(2026, 11, 15))], NOW, false);
    expect(agenda.days.map((d) => d.label)).toEqual(["Today", "Tomorrow", "Sat, Nov 14"]);
    expect(timeText(agenda.days[2]?.rows[0] ?? fail())).toBe("All day");
  });
});

describe("buildAgenda: in progress, next and past", () => {
  const rows = [
    row("done", at(2026, 11, 12, 9), at(2026, 11, 12, 10)),
    row("now", at(2026, 11, 12, 15), at(2026, 11, 12, 16)),
    row("next", at(2026, 11, 12, 17), at(2026, 11, 12, 18)),
    row("later", at(2026, 11, 12, 19), at(2026, 11, 12, 20)),
  ];

  it("marks the event in progress Now and the following one Next", () => {
    const agenda = buildAgenda(rows, NOW, false);
    expect(agenda.days[0]?.rows.map((r) => [r.event.id, r.marker])).toEqual([
      ["now", "now"],
      ["next", "next"],
      ["later", null],
    ]);
  });

  it("hides events already over unless asked, and then still marks correctly", () => {
    expect(ids(buildAgenda(rows, NOW, false).days[0]?.rows ?? [])).not.toContain("done");
    const all = buildAgenda(rows, NOW, true).days[0]?.rows ?? [];
    expect(all.map((r) => [r.event.id, r.marker])).toEqual([
      ["done", null],
      ["now", "now"],
      ["next", "next"],
      ["later", null],
    ]);
  });

  it("marks every overlapping event in progress Now", () => {
    const agenda = buildAgenda([row("a", at(2026, 11, 12, 15), at(2026, 11, 12, 16)), row("b", at(2026, 11, 12, 14), at(2026, 11, 12, 17))], NOW, false);
    expect(agenda.days[0]?.rows.map((r) => r.marker)).toEqual(["now", "now"]);
  });

  it("an event ending exactly now is over; one starting exactly now is not in progress but upcoming-or-now", () => {
    const agenda = buildAgenda([row("ends", at(2026, 11, 12, 14), NOW), row("starts", NOW, at(2026, 11, 12, 16))], NOW, false);
    expect(agenda.days[0]?.rows.map((r) => [r.event.id, r.marker])).toEqual([["starts", "now"]]);
  });

  it("never marks an all-day event Now or Next", () => {
    const agenda = buildAgenda([row("all", at(2026, 11, 12), at(2026, 11, 13))], NOW, false);
    expect(agenda.days[0]?.rows[0]?.marker).toBeNull();
  });

  it("marks Next on tomorrow's first event when nothing more is left today", () => {
    const agenda = buildAgenda([row("tm", at(2026, 11, 13, 8))], NOW, false);
    expect(agenda.days[0]?.rows[0]?.marker).toBe("next");
  });

  it("keeps a point event today after its start only when past events are included", () => {
    const point = row("p", at(2026, 11, 12, 9));
    expect(buildAgenda([point], NOW, false).total).toBe(0);
    expect(buildAgenda([point], NOW, true).total).toBe(1);
  });

  it("keeps an all-day event today all day, even late in the evening", () => {
    const evening = at(2026, 11, 12, 23, 30);
    expect(buildAgenda([row("all", at(2026, 11, 12), at(2026, 11, 13))], evening, false).total).toBe(1);
  });
});

describe("buildAgenda: DST", () => {
  it("on the 25 hour fall-back day, keeps 11:30 PM in Today and the next 12:30 AM in Tomorrow", () => {
    const now = at(2026, 11, 1, 22);
    const agenda = buildAgenda([row("a", at(2026, 11, 1, 23, 30)), row("b", at(2026, 11, 2, 0, 30))], now, false);
    expect(agenda.days.map((d) => [d.label, ids(d.rows)])).toEqual([
      ["Today", ["a"]],
      ["Tomorrow", ["b"]],
    ]);
  });

  it("on the 23 hour spring-forward day, an all-day event is one Today row and Tomorrow is the 9th", () => {
    const now = at(2026, 3, 8, 12);
    const agenda = buildAgenda([row("all", at(2026, 3, 8), at(2026, 3, 9)), row("n", at(2026, 3, 9, 9))], now, false);
    expect(agenda.days.map((d) => [d.label, ids(d.rows)])).toEqual([
      ["Today", ["all"]],
      ["Tomorrow", ["n"]],
    ]);
    expect(agendaLabel(at(2026, 3, 9), now)).toBe("Tomorrow");
  });

  it("labels the day after tomorrow by date across the fall-back change", () => {
    expect(agendaLabel(at(2026, 11, 3), at(2026, 11, 1, 12))).toBe("Tue, Nov 3");
  });
});

describe("tiers and limits", () => {
  const many = Array.from({ length: 10 }, (_, i) => row(`e${String(i).padStart(2, "0")}`, at(2026, 11, 12, 16 + (i % 7), i)));
  const rowsOnTomorrow = [row("tm", at(2026, 11, 13, 9)), row("later", at(2026, 11, 16, 9))];

  it("limits rows by height tier and counts the rest as more", () => {
    const agenda = buildAgenda(many, NOW, false);
    expect(rowLimit(1)).toBeLessThan(rowLimit(2));
    expect(rowLimit(2)).toBeLessThan(rowLimit(3));
    const h1 = limitAgenda(agenda, 1);
    expect(h1.days.flatMap((d) => d.rows)).toHaveLength(rowLimit(1));
    expect(h1.more).toBe(10 - rowLimit(1));
    expect(limitAgenda(agenda, 2).more).toBe(10 - rowLimit(2));
    expect(limitAgenda(agenda, 3).more).toBe(0);
  });

  it("stops at tomorrow below height tier 3 and counts later days as more", () => {
    const agenda = buildAgenda([...many.slice(0, 1), ...rowsOnTomorrow], NOW, false);
    const h2 = limitAgenda(agenda, 2);
    expect(h2.days.map((d) => d.label)).toEqual(["Today", "Tomorrow"]);
    expect(h2.more).toBe(1);
    expect(limitAgenda(agenda, 3).days.map((d) => d.label)).toEqual(["Today", "Tomorrow", "Mon, Nov 16"]);
  });

  it("drops a day whose rows all fall past the limit", () => {
    const agenda = buildAgenda([row("a", at(2026, 11, 12, 16)), row("b", at(2026, 11, 12, 17)), row("tm", at(2026, 11, 13, 9))], NOW, false);
    expect(limitAgenda(agenda, 1).days.map((d) => d.label)).toEqual(["Today"]);
  });

  it("gates detail and markers by width tier, and past events by height tier", () => {
    expect([1, 2, 3].map((w) => showsDetail(w as 1 | 2 | 3))).toEqual([false, true, true]);
    expect([1, 2, 3].map((w) => showsMarkers(w as 1 | 2 | 3))).toEqual([false, false, true]);
    expect([1, 2, 3].map((h) => showsPast(h as 1 | 2 | 3))).toEqual([false, false, true]);
  });
});

describe("text", () => {
  const first = (r: EventRow) => buildAgenda([r], at(2026, 11, 12, 0, 1), true).days[0]?.rows[0] ?? fail();

  it("writes 12-hour times, including midnight and noon", () => {
    expect(timeText(first(row("a", at(2026, 11, 12, 0, 30), at(2026, 11, 12, 1))))).toBe("12:30 AM");
    expect(timeText(first(row("b", at(2026, 11, 12, 12, 0), at(2026, 11, 12, 13))))).toBe("12:00 PM");
    expect(timeText(first(row("c", at(2026, 11, 12, 15, 5), at(2026, 11, 12, 16))))).toBe("3:05 PM");
  });

  it("writes until-times only for timed events with an end", () => {
    expect(untilText(first(row("a", at(2026, 11, 12, 9), at(2026, 11, 12, 10, 30))))).toBe("until 10:30 AM");
    expect(untilText(first(row("b", at(2026, 11, 12, 9))))).toBe("");
    expect(untilText(first(row("c", at(2026, 11, 12), at(2026, 11, 13))))).toBe("");
  });
});

function fail(): never {
  throw new Error("missing row");
}
