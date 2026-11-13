import type { components } from "../../api/generated/schema";
import type { ApiErrorKind } from "../../api/errors";

export type ApiSummary = components["schemas"]["SummaryResult"];

/** Longest string shown, in characters. The API caps a string at 300; this is tighter, and holds if the API changes. */
export const CLIP = 200;
/** At most this many entries are read from a list (the API caps a list at 10). */
const LIST_MAX = 10;

export type Cols = 4 | 8 | 12;
export type SummaryKind = "fresh" | "stored" | "template";

export interface SummaryModel {
  readonly headline: string;
  readonly priorities: readonly string[];
  readonly headsUp: readonly string[];
  readonly kind: SummaryKind;
  /** The provider's name as the API sent it; only read for a fresh summary. */
  readonly provider: string;
}

/** Control characters and bidirectional overrides can reorder or hide text, so they are removed (the text comes from
 *  feeds and mail). Whitespace runs collapse to one space. */
// eslint-disable-next-line no-control-regex -- removing control characters is the point
const UNSAFE = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g;

export function clip(text: string, max: number = CLIP): string {
  const chars = Array.from(text);
  return chars.length <= max ? text : `${chars.slice(0, max - 1).join("").trimEnd()}…`;
}

/** Plain text for display: unsafe characters gone, whitespace collapsed, clipped. Never HTML. */
export function cleanText(value: unknown): string {
  return typeof value === "string" ? clip(value.replace(UNSAFE, "").replace(/\s+/g, " ").trim()) : "";
}

function cleanList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return (value as unknown[])
    .slice(0, LIST_MAX)
    .map(cleanText)
    .filter((text) => text !== "");
}

/** Read a response into only the fields the card uses; extra fields are ignored. Null when it is not a summary. */
export function parseSummary(data: unknown): SummaryModel | null {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const body = data as Record<string, unknown>;
  const inner = body["summary"];
  if (typeof inner !== "object" || inner === null) return null;
  const summary = inner as Record<string, unknown>;
  const headline = cleanText(summary["headline"]);
  if (headline === "") return null;
  const provider = typeof body["provider"] === "string" ? body["provider"] : "";
  return {
    headline,
    priorities: cleanList(summary["priorities"]),
    headsUp: cleanList(summary["heads_up"]),
    kind: provider === "stored" ? "stored" : provider === "template" ? "template" : "fresh",
    provider,
  };
}

/** The local calendar day as YYYY-MM-DD. The clock is a parameter. */
export function summaryDay(nowMs: number): string {
  const d = new Date(nowMs);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export type HeadsUpPlacement = "none" | "below" | "beside";

/** What each column count shows (decision 0381): 4 columns: headline and up to 3 priorities; 8: up to 4 and the
 *  heads-up below; 12: up to 5 and the heads-up beside. */
export function tierFor(cols: Cols): { readonly priorities: number; readonly headsUp: HeadsUpPlacement } {
  if (cols >= 12) return { priorities: 5, headsUp: "beside" };
  if (cols >= 8) return { priorities: 4, headsUp: "below" };
  return { priorities: 3, headsUp: "none" };
}

export function limitPriorities(
  priorities: readonly string[],
  cols: Cols,
): { readonly shown: readonly string[]; readonly more: number } {
  const max = tierFor(cols).priorities;
  return { shown: priorities.slice(0, max), more: Math.max(0, priorities.length - max) };
}

/** Fixed notice for a fallback summary. The API gives no date for a stored one, so none is shown. */
export function fallbackNotice(kind: SummaryKind): string | null {
  if (kind === "stored") return "Showing an earlier summary";
  if (kind === "template") return "Showing a basic summary";
  return null;
}

export interface SummarySnapshot {
  readonly isPending: boolean;
  readonly isError: boolean;
  /** Kind of the failure, when it is an ApiError. */
  readonly errorKind: ApiErrorKind | null;
  /** Null while there is no data, or when the data is not a summary. */
  readonly model: SummaryModel | null;
  readonly hasData: boolean;
}

export type SummaryState =
  | { readonly kind: "loading" }
  | { readonly kind: "off" }
  | { readonly kind: "error" }
  | { readonly kind: "ready"; readonly model: SummaryModel; readonly refreshFailed: boolean };

/** The 404 (summaries are off) is its own state; every other failure, and a body that is not a summary, is the error. */
export function deriveSummaryState(s: SummarySnapshot): SummaryState {
  if (s.model) return { kind: "ready", model: s.model, refreshFailed: s.isError };
  if (s.hasData) return { kind: "error" };
  if (s.isError) return s.errorKind === "not_found" ? { kind: "off" } : { kind: "error" };
  return s.isPending ? { kind: "loading" } : { kind: "error" };
}
