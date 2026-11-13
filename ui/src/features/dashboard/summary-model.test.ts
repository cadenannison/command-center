import { describe, expect, it } from "vitest";
import {
  CLIP,
  clip,
  cleanText,
  deriveSummaryState,
  fallbackNotice,
  limitPriorities,
  parseSummary,
  summaryDay,
  tierFor,
  type SummaryModel,
  type SummarySnapshot,
} from "./summary-model";

const body = (summary: Record<string, unknown>, provider = "gemini") => ({ summary, provider, cached: false });

describe("summaryDay", () => {
  it("is the local calendar day, with the clock as a parameter", () => {
    expect(summaryDay(new Date(2026, 10, 12, 0, 5).getTime())).toBe("2026-11-12");
    expect(summaryDay(new Date(2026, 10, 12, 23, 59).getTime())).toBe("2026-11-12");
    expect(summaryDay(new Date(2026, 0, 3, 12).getTime())).toBe("2026-01-03");
  });

  it("uses the local day, not the UTC day, late in the evening", () => {
    // 9:30 PM in Denver on Nov 12 is already Nov 13 in UTC.
    const t = new Date(2026, 10, 12, 21, 30).getTime();
    expect(new Date(t).toISOString().slice(0, 10)).toBe("2026-11-13");
    expect(summaryDay(t)).toBe("2026-11-12");
  });
});

describe("tierFor and limitPriorities", () => {
  it("4 columns: 3 priorities, no heads-up; 8: 4 and below; 12: 5 and beside", () => {
    expect(tierFor(4)).toEqual({ priorities: 3, headsUp: "none" });
    expect(tierFor(8)).toEqual({ priorities: 4, headsUp: "below" });
    expect(tierFor(12)).toEqual({ priorities: 5, headsUp: "beside" });
  });

  it("counts what is cut as +N more", () => {
    const six = ["a", "b", "c", "d", "e", "f"];
    expect(limitPriorities(six, 4)).toEqual({ shown: ["a", "b", "c"], more: 3 });
    expect(limitPriorities(six, 8)).toEqual({ shown: ["a", "b", "c", "d"], more: 2 });
    expect(limitPriorities(six, 12)).toEqual({ shown: ["a", "b", "c", "d", "e"], more: 1 });
    expect(limitPriorities(["a", "b"], 4)).toEqual({ shown: ["a", "b"], more: 0 });
  });
});

describe("fallbackNotice", () => {
  it("names a stored or template summary and says nothing for a fresh one", () => {
    expect(fallbackNotice("stored")).toBe("Showing an earlier summary");
    expect(fallbackNotice("template")).toBe("Showing a basic summary");
    expect(fallbackNotice("fresh")).toBeNull();
  });
});

describe("clip and cleanText", () => {
  it("clips long strings to CLIP characters with an ellipsis, counting characters not code units", () => {
    const long = "x".repeat(5000);
    const out = clip(long);
    expect(Array.from(out)).toHaveLength(CLIP);
    expect(out.endsWith("…")).toBe(true);
    const emoji = "😀".repeat(CLIP + 5);
    expect(Array.from(clip(emoji))).toHaveLength(CLIP);
    expect(clip("short")).toBe("short");
  });

  it("removes control and bidirectional override characters and collapses whitespace", () => {
    const dirty = ["a", String.fromCharCode(0), "b", String.fromCharCode(0x202e), "c", String.fromCharCode(0x2066), "d", String.fromCharCode(0x200b), "e"].join("");
    expect(cleanText(dirty)).toBe("abcde");
    expect(cleanText("  one \n\t two   three ")).toBe("one two three");
    expect(cleanText(42)).toBe("");
  });

  it("leaves HTML-looking text as it is: it is only ever rendered as text", () => {
    expect(cleanText("<img src=x onerror=alert(1)> & <b>bold</b>")).toBe("<img src=x onerror=alert(1)> & <b>bold</b>");
  });
});

describe("parseSummary", () => {
  it("reads headline, priorities, heads-up and the kind", () => {
    const m = parseSummary(body({ headline: "Busy day", priorities: ["a"], heads_up: ["b"] }, "gemini"));
    expect(m).toEqual({ headline: "Busy day", priorities: ["a"], headsUp: ["b"], kind: "fresh", provider: "gemini" });
    expect(parseSummary(body({ headline: "h" }, "stored"))?.kind).toBe("stored");
    expect(parseSummary(body({ headline: "h" }, "template"))?.kind).toBe("template");
  });

  it("ignores unexpected extra fields, at the top and inside the summary", () => {
    const m = parseSummary({
      summary: { headline: "h", priorities: [], heads_up: [], secret: "s", html: "<b>x</b>" },
      provider: "ollama",
      cached: true,
      debug: { token: "t" },
    });
    expect(m).toEqual({ headline: "h", priorities: [], headsUp: [], kind: "fresh", provider: "ollama" });
    expect(JSON.stringify(m)).not.toContain("secret");
    expect(JSON.stringify(m)).not.toContain("token");
  });

  it("drops entries that are not strings or are empty, and reads at most ten", () => {
    const many = Array.from({ length: 30 }, (_, i) => `p${String(i)}`);
    const m = parseSummary(body({ headline: "h", priorities: [1, null, "  ", "ok", {}], heads_up: many }));
    expect(m?.priorities).toEqual(["ok"]);
    expect(m?.headsUp).toHaveLength(10);
  });

  it("is null for anything that is not a summary", () => {
    for (const bad of [null, undefined, [], "x", 3, {}, { summary: null }, { summary: {} }, { summary: { headline: "  " } }, { summary: { headline: 5 } }]) {
      expect(parseSummary(bad)).toBeNull();
    }
  });
});

describe("deriveSummaryState", () => {
  const model: SummaryModel = { headline: "h", priorities: [], headsUp: [], kind: "fresh", provider: "gemini" };
  const snap = (over: Partial<SummarySnapshot>): SummarySnapshot => ({
    isPending: false,
    isError: false,
    errorKind: null,
    model: null,
    hasData: false,
    ...over,
  });

  it("is loading while pending with nothing to show", () => {
    expect(deriveSummaryState(snap({ isPending: true }))).toEqual({ kind: "loading" });
  });

  it("tells the 404 (off) apart from every other failure", () => {
    expect(deriveSummaryState(snap({ isError: true, errorKind: "not_found" }))).toEqual({ kind: "off" });
    for (const kind of ["network", "server", "validation", "unauthorized", "forbidden", "rate_limited", "unknown"] as const) {
      expect(deriveSummaryState(snap({ isError: true, errorKind: kind }))).toEqual({ kind: "error" });
    }
    expect(deriveSummaryState(snap({ isError: true, errorKind: null }))).toEqual({ kind: "error" });
  });

  it("is an error when the body is not a summary", () => {
    expect(deriveSummaryState(snap({ hasData: true, model: null }))).toEqual({ kind: "error" });
  });

  it("keeps showing the summary when a refresh fails", () => {
    expect(deriveSummaryState(snap({ model, hasData: true }))).toEqual({ kind: "ready", model, refreshFailed: false });
    expect(deriveSummaryState(snap({ model, hasData: true, isError: true, errorKind: "server" }))).toEqual({
      kind: "ready",
      model,
      refreshFailed: true,
    });
  });
});
