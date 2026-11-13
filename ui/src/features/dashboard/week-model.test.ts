import { describe, expect, it } from "vitest";
import type { ApiEvent } from "./use-events";
import {
  buildWeek,
  countText,
  dayLabel,
  eventSourceId,
  firstDayFromIntl,
  itemsPerDay,
  localFirstDay,
  localMidnight,
  showsNext,
  weekItemsOf,
  weekStart,
  weekWindow,
  type WeekItem,
} from "./week-model";

// Day boundaries and DST need a zone with DST. Set before any Date is built; the first test proves it took effect.
process.env["TZ"] = "America/Denver";

const at = (y: number, m: number, d: number, h = 0, min = 0) => new Date(y, m - 1, d, h, min).getTime();
const HOUR = 3_600_000;

const item = (id: string, startMs: number, endMs: number | null = null, source: WeekItem["source"] = "cal"): WeekItem => ({
  id,
  title: `Item ${id}`,
  startMs,
  endMs,
  source,
});

const event = (id: string, start: string | null, extra: Partial<ApiEvent> = {}): ApiEvent => ({
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

describe("the test zone", () => {
  it("is America/Denver, so the DST cases below are real", () => {
    expect(new Date(2026, 0, 15).getTimezoneOffset()).toBe(420);
    expect(new Date(2026, 6, 15).getTimezoneOffset()).toBe(360);
  });
});

describe("weekStart and weekWindow", () => {
  // Thursday, Nov 12, 2026.
  const now = at(2026, 11, 12, 15, 30);

  it("starts the week on the given local first day", () => {
    expect(weekStart(now, 0)).toBe(at(2026, 11, 8)); // Sunday
    expect(weekStart(now, 1)).toBe(at(2026, 11, 9)); // Monday
    expect(weekStart(now, 6)).toBe(at(2026, 11, 7)); // Saturday
    expect(weekStart(now, 4)).toBe(at(2026, 11, 12)); // today is the first day
  });

  it("asks for seven local days: [start, start + 7 calendar days)", () => {
    expect(weekWindow(now, 1)).toEqual({
      from: new Date(at(2026, 11, 9)).toISOString(),
      to: new Date(at(2026, 11, 16)).toISOString(),
    });
  });

  it("is a whole week of calendar days across the fall-back change (a 25 hour day)", () => {
    const sundayOfChange = at(2026, 11, 1, 12);
    const { from, to } = weekWindow(sundayOfChange, 0);
    expect(from).toBe(new Date(at(2026, 11, 1)).toISOString());
    expect(to).toBe(new Date(at(2026, 11, 8)).toISOString());
    expect((Date.parse(to) - Date.parse(from)) / HOUR).toBe(7 * 24 + 1);
  });

  it("is a whole week of calendar days across the spring-forward change (a 23 hour day)", () => {
    const { from, to } = weekWindow(at(2026, 3, 11, 12), 0);
    expect(from).toBe(new Date(at(2026, 3, 8)).toISOString());
    expect((Date.parse(to) - Date.parse(from)) / HOUR).toBe(7 * 24 - 1);
  });
});

describe("first weekday from the locale", () => {
  it("maps Intl's 1 to 7 (Monday to Sunday) to Date's 0 to 6", () => {
    expect(firstDayFromIntl(7)).toBe(0);
    expect(firstDayFromIntl(1)).toBe(1);
    expect(firstDayFromIntl(6)).toBe(6);
  });

  it("falls back to Sunday for anything unreadable", () => {
    for (const bad of [undefined, 0, 8, 1.5, Number.NaN]) expect(firstDayFromIntl(bad)).toBe(0);
    expect(localFirstDay("not a locale !!")).toBe(0);
  });

  it("reads a real locale when the runtime has week info", () => {
    expect([0, 1]).toContain(localFirstDay("en-US"));
    expect(localFirstDay("en-US")).toBe(0);
  });
});

describe("buildWeek", () => {
  const now = at(2026, 11, 12, 15, 30); // Thursday

  it("makes seven local days in order and marks only today", () => {
    const week = buildWeek([], now, 0);
    expect(week.days.map((d) => d.weekday)).toEqual(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]);
    expect(week.days.map((d) => d.dayOfMonth)).toEqual([8, 9, 10, 11, 12, 13, 14]);
    expect(week.days.filter((d) => d.isToday).map((d) => d.weekday)).toEqual(["Thu"]);
    expect(week.total).toBe(0);
    expect(week.next).toBeNull();
  });

  it("rotates for a Monday start", () => {
    const week = buildWeek([], now, 1);
    expect(week.days.map((d) => d.weekday)[0]).toBe("Mon");
    expect(week.days.map((d) => d.dayOfMonth)).toEqual([9, 10, 11, 12, 13, 14, 15]);
  });

  it("puts 11:59 PM in its day and 12:00 AM in the next", () => {
    const week = buildWeek([item("late", at(2026, 11, 12, 23, 59)), item("early", at(2026, 11, 13, 0, 0))], now, 0);
    expect(week.days[4]?.items.map((i) => i.id)).toEqual(["late"]);
    expect(week.days[5]?.items.map((i) => i.id)).toEqual(["early"]);
  });

  it("counts a multi-day item on each day it overlaps, but an end at midnight does not reach the next day", () => {
    const trip = item("trip", at(2026, 11, 9, 18), at(2026, 11, 11, 9));
    const allDay = item("all-day", at(2026, 11, 10), at(2026, 11, 11));
    const week = buildWeek([trip, allDay], now, 0);
    expect(week.days.map((d) => d.items.length)).toEqual([0, 1, 2, 1, 0, 0, 0]);
    expect(week.days[3]?.items.map((i) => i.id)).toEqual(["trip"]);
    expect(week.total).toBe(4);
  });

  it("keeps items in time order inside a day and lists each source once", () => {
    const week = buildWeek(
      [item("b", at(2026, 11, 12, 14), null, "canvas"), item("a", at(2026, 11, 12, 9)), item("c", at(2026, 11, 12, 16), null, "canvas")],
      now,
      0,
    );
    expect(week.days[4]?.items.map((i) => i.id)).toEqual(["a", "b", "c"]);
    expect(week.days[4]?.sources).toEqual(["cal", "canvas"]);
  });

  it("ignores items outside the week", () => {
    const week = buildWeek([item("before", at(2026, 11, 7, 12)), item("after", at(2026, 11, 15, 12))], now, 0);
    expect(week.total).toBe(0);
  });

  it("finds the next event: the first one not over yet, and says when it is under way", () => {
    const over = item("over", at(2026, 11, 12, 9), at(2026, 11, 12, 10));
    const upcoming = item("upcoming", at(2026, 11, 12, 17));
    const later = item("later", at(2026, 11, 13, 8));
    expect(buildWeek([over, upcoming, later], now, 0).next).toEqual({ item: upcoming, ongoing: false });
    const underway = item("underway", at(2026, 11, 12, 15), at(2026, 11, 12, 16));
    expect(buildWeek([over, underway, upcoming], now, 0).next).toEqual({ item: underway, ongoing: true });
  });

  it("treats an event that starts exactly now as upcoming-and-now, and one that ended exactly now as over", () => {
    const starting = item("starting", now);
    expect(buildWeek([starting], now, 0).next).toEqual({ item: starting, ongoing: true });
    const ended = item("ended", now - HOUR, now);
    expect(buildWeek([ended], now, 0).next).toBeNull();
  });

  it("assigns days by the local calendar across the fall-back change", () => {
    const sunday = at(2026, 11, 1, 12);
    const items = [
      item("night-before", at(2026, 11, 1, 23, 30)),
      item("monday", at(2026, 11, 2, 0, 0)),
      // 1:30 AM happens twice on Nov 1; the second one is one hour of real time later, still Sunday.
      item("second-1-30", new Date(2026, 10, 1, 1, 30).getTime() + HOUR),
    ];
    const week = buildWeek(items, sunday, 0);
    expect(week.days[0]?.items.map((i) => i.id)).toEqual(["second-1-30", "night-before"]);
    expect(week.days[1]?.items.map((i) => i.id)).toEqual(["monday"]);
    expect(week.days[0]?.isToday).toBe(true);
    expect((week.days[0]?.endMs ?? 0) - (week.days[0]?.startMs ?? 0)).toBe(25 * HOUR);
  });

  it("assigns days by the local calendar across the spring-forward change", () => {
    const wednesday = at(2026, 3, 11, 12);
    const week = buildWeek([item("sun-late", at(2026, 3, 8, 23, 30)), item("mon", at(2026, 3, 9))], wednesday, 0);
    expect(week.days[0]?.items.map((i) => i.id)).toEqual(["sun-late"]);
    expect(week.days[1]?.items.map((i) => i.id)).toEqual(["mon"]);
    expect((week.days[0]?.endMs ?? 0) - (week.days[0]?.startMs ?? 0)).toBe(23 * HOUR);
    expect(week.days.map((d) => d.dayOfMonth)).toEqual([8, 9, 10, 11, 12, 13, 14]);
  });

  it("is today at 12:00 AM and 11:59 PM of the same day, and not at the next midnight", () => {
    expect(buildWeek([], at(2026, 11, 12, 0, 0), 0).days[4]?.isToday).toBe(true);
    expect(buildWeek([], at(2026, 11, 12, 23, 59), 0).days[4]?.isToday).toBe(true);
    expect(buildWeek([], at(2026, 11, 13, 0, 0), 0).days[4]?.isToday).toBe(false);
  });
});

describe("weekItemsOf", () => {
  it("keeps calendar events (any calendar feed) when Calendar is a source", () => {
    const items = weekItemsOf([event("e1", "2026-11-12T16:00:00Z", { end: "2026-11-12T17:00:00Z" })], ["cal"]);
    expect(items).toEqual([
      { id: "e1", title: "Event e1", startMs: Date.parse("2026-11-12T16:00:00Z"), endMs: Date.parse("2026-11-12T17:00:00Z"), source: "cal" },
    ]);
  });

  it("leaves weather, done and timeless items out, and sorts by time", () => {
    const items = weekItemsOf(
      [
        event("w", "2026-11-12T00:00:00Z", { kind: "weather", source: "weather" }),
        event("done", "2026-11-12T10:00:00Z", { status: "done" }),
        event("none", null),
        event("junk", "not a date"),
        event("b", "2026-11-13T10:00:00Z"),
        event("a", "2026-11-12T10:00:00Z"),
      ],
      ["cal"],
    );
    expect(items.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("ignores an end that is not after the start", () => {
    const [only] = weekItemsOf([event("e", "2026-11-12T16:00:00Z", { end: "2026-11-12T16:00:00Z" })], ["cal"]);
    expect(only?.endMs).toBeNull();
  });

  it("includes other open items by due time only when their source is selected", () => {
    const assignment = event("hw", null, { kind: "assignment", source: "canvas", due: "2026-11-13T18:00:00Z" });
    expect(weekItemsOf([assignment], ["cal"])).toEqual([]);
    const [kept] = weekItemsOf([assignment], ["cal", "canvas"]);
    expect(kept).toMatchObject({ id: "hw", source: "canvas", startMs: Date.parse("2026-11-13T18:00:00Z"), endMs: null });
  });

  it("does not count calendar events when Calendar is not a source", () => {
    expect(weekItemsOf([event("e", "2026-11-12T16:00:00Z")], ["canvas"])).toEqual([]);
  });
});

describe("small helpers", () => {
  it("maps a source to a design source", () => {
    expect(eventSourceId("canvas", "assignment")).toBe("canvas");
    expect(eventSourceId("apple_calendar", "event")).toBe("cal");
    expect(eventSourceId("local", "task")).toBe("manual");
  });

  it("shows the next line from height tier 2 and day items only at tier 3", () => {
    expect([1, 2, 3].map((t) => showsNext(t as 1 | 2 | 3))).toEqual([false, true, true]);
    expect([1, 2, 3].map((t) => itemsPerDay(t as 1 | 2 | 3))).toEqual([0, 0, 3]);
  });

  it("writes counts and a day name for a screen reader", () => {
    expect([0, 1, 4].map(countText)).toEqual(["No events", "1 event", "4 events"]);
    const day = buildWeek([], at(2026, 11, 12), 0).days[4];
    expect(day && dayLabel(day)).toBe("Thursday, November 12");
    expect(localMidnight(at(2026, 11, 12, 15), 1)).toBe(at(2026, 11, 13));
  });
});
