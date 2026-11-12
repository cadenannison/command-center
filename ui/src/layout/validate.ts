import { clampItemTo12, compactForSanitize, MAX_Y } from "./sanitize-grid";
import { getWidget, isCrossKind, kindOfSource, SOURCE_ORDER } from "./registry";
import type { SourceId } from "../lib/sources";
import { LAYOUT_VERSION, type Layout, type LayoutItem, type OptionValue, type WidgetDefinition } from "./types";

export const MAX_ITEMS = 50;
export const MAX_JSON_CHARS = 200_000;
const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_OPTIONS = 20;
const MAX_OPTION_KEY = 40;
const MAX_OPTION_STRING = 200;
const UNSAFE_KEYS = new Set(["__proto__", "constructor", "prototype"]);

export type LayoutErrorCode = "too_large" | "not_json" | "not_an_object" | "missing_version" | "unsupported_version" | "bad_items";

export interface LayoutError {
  readonly code: LayoutErrorCode;
  readonly message: string;
}

export type WarningCode =
  | "item_not_an_object"
  | "bad_id"
  | "duplicate_id"
  | "unknown_widget"
  | "bad_geometry"
  | "too_many_items"
  | "sources_adjusted"
  | "pinned_overlap";

export interface LayoutWarning {
  readonly code: WarningCode;
  /** Index of the item in the input, when the warning is about one item. */
  readonly index: number;
}

export type LayoutResult =
  | { readonly ok: true; readonly layout: Layout; readonly warnings: readonly LayoutWarning[] }
  | { readonly ok: false; readonly error: LayoutError };

/** A migration turns a layout of version n into version n + 1. Keyed by n. None exist yet (version 1 is first). */
export type Migrations = Readonly<Record<number, (raw: Record<string, unknown>) => Record<string, unknown>>>;
export const MIGRATIONS: Migrations = {};

function fail(code: LayoutErrorCode, message: string): { readonly ok: false; readonly error: LayoutError } {
  return { ok: false, error: { code, message } };
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Bring raw layout data up to the current version. An unknown or newer version is an error, never a guess. */
export type Migrated = { readonly ok: true; readonly raw: Record<string, unknown> } | { readonly ok: false; readonly error: LayoutError };

export function migrateLayout(raw: unknown, migrations: Migrations = MIGRATIONS, target: number = LAYOUT_VERSION): Migrated {
  if (!isRecord(raw)) return fail("not_an_object", "A layout must be an object.");
  let version = raw.version;
  if (typeof version !== "number" || !Number.isInteger(version)) return fail("missing_version", "A layout needs an integer version.");
  if (version > target || version < 1) return fail("unsupported_version", `Layout version ${String(version)} is not supported.`);
  let current: Record<string, unknown> = raw;
  while (version < target) {
    const step = migrations[version];
    if (!step) return fail("unsupported_version", `No migration from layout version ${String(version)}.`);
    version += 1;
    current = { ...step(current), version };
  }
  return { ok: true, raw: current };
}

function isSourceId(value: unknown): value is SourceId {
  return typeof value === "string" && (SOURCE_ORDER as readonly string[]).includes(value);
}

/** Allowed, de-duplicated sources in registry order, obeying the kind rule; the default set if none survive. */
function sanitizeSources(def: WidgetDefinition, raw: unknown): SourceId[] {
  const wanted = new Set(Array.isArray(raw) ? (raw as unknown[]).filter(isSourceId) : []);
  let sources = SOURCE_ORDER.filter((s) => wanted.has(s) && def.allowedSources.includes(s));
  // Layout validity must not depend on the owed-replies toggle, so gmail counts as tasks here (decision 0350).
  const kind = kindOfSource(sources[0] ?? "cal", true);
  if (!isCrossKind(def.kind)) sources = sources.filter((s) => kindOfSource(s, true) === kind);
  return sources.length > 0 ? sources : [...def.defaultSources];
}

function sanitizeOptions(raw: unknown): Record<string, OptionValue> {
  const out: Record<string, OptionValue> = {};
  if (!isRecord(raw)) return out;
  for (const [key, value] of Object.entries(raw)) {
    if (Object.keys(out).length >= MAX_OPTIONS) break;
    if (UNSAFE_KEYS.has(key) || key.length === 0 || key.length > MAX_OPTION_KEY) continue;
    if (typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) out[key] = value;
    else if (typeof value === "string" && value.length <= MAX_OPTION_STRING) out[key] = value;
  }
  return out;
}

const same = (a: readonly unknown[], b: readonly unknown[]): boolean => a.length === b.length && a.every((v, i) => v === b[i]);

/** Parse and clean one raw item. Returns a code for an item that must be dropped. */
function sanitizeItem(raw: unknown, warn: (code: WarningCode) => void): LayoutItem | WarningCode {
  if (!isRecord(raw)) return "item_not_an_object";
  if (typeof raw.id !== "string" || !ID_PATTERN.test(raw.id)) return "bad_id";
  const def = typeof raw.widgetId === "string" ? getWidget(raw.widgetId) : undefined;
  if (!def) return "unknown_widget";
  const { x, y, w, h } = raw;
  if (![x, y, w, h].every((n) => typeof n === "number" && Number.isFinite(n))) return "bad_geometry";
  const box = clampItemTo12(def, { x: Math.round(x as number), y: Math.round(y as number), w: Math.round(w as number), h: Math.round(h as number) });
  const sources = sanitizeSources(def, raw.sources);
  if (Array.isArray(raw.sources) && !same(sources, raw.sources as unknown[])) warn("sources_adjusted");
  return {
    id: raw.id,
    widgetId: def.id,
    ...box,
    pinned: raw.pinned === true,
    sources,
    options: sanitizeOptions(raw.options),
  };
}

/** Clean untrusted layout data into a valid current-version layout, with a warning for each change. */
export function sanitizeLayout(raw: unknown, migrations: Migrations = MIGRATIONS): LayoutResult {
  const result = migrateLayout(raw, migrations);
  if (!result.ok) return result;
  const migrated = result.raw;
  if (!Array.isArray(migrated.items)) return fail("bad_items", "A layout needs an items list.");
  const warnings: LayoutWarning[] = [];
  const items: LayoutItem[] = [];
  const seen = new Set<string>();
  const input = migrated.items as unknown[];
  input.forEach((rawItem, index) => {
    const result = sanitizeItem(rawItem, (code) => warnings.push({ code, index }));
    if (typeof result === "string") return warnings.push({ code: result, index });
    if (seen.has(result.id)) return warnings.push({ code: "duplicate_id", index });
    if (items.length >= MAX_ITEMS) return warnings.push({ code: "too_many_items", index });
    seen.add(result.id);
    items.push(result);
  });
  const { items: compacted, unpinned } = compactForSanitize(items);
  // Pushing down can carry an item past MAX_Y; it is dropped so a second pass changes nothing.
  const settled = compacted.filter((i) => i.y <= MAX_Y);
  for (const dropped of compacted.filter((i) => i.y > MAX_Y)) {
    warnings.push({ code: "too_many_items", index: input.findIndex((r) => isRecord(r) && r.id === dropped.id) });
  }
  for (const id of unpinned) warnings.push({ code: "pinned_overlap", index: input.findIndex((r) => isRecord(r) && r.id === id) });
  return { ok: true, layout: { version: LAYOUT_VERSION, items: settled }, warnings };
}

/** Parse layout JSON text (an import or a stored value) and sanitize it. */
export function parseLayoutJson(text: string): LayoutResult {
  if (text.length > MAX_JSON_CHARS) return fail("too_large", "That layout is too large.");
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return fail("not_json", "That is not valid JSON.");
  }
  return sanitizeLayout(raw);
}

/** Stable JSON for a layout (fixed key order), so parse(serialize(x)) equals x. */
export function serializeLayout(layout: Layout): string {
  return JSON.stringify({
    version: layout.version,
    items: layout.items.map((i) => ({
      id: i.id,
      widgetId: i.widgetId,
      x: i.x,
      y: i.y,
      w: i.w,
      h: i.h,
      pinned: i.pinned,
      sources: i.sources,
      options: i.options,
    })),
  });
}
