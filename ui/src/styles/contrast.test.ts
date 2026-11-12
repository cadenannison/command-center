import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// WCAG contrast of every token pair that is used together (task T1b, decision 0345). tokens.css is parsed
// the way the browser cascades it, so no browser is needed. Translucent fills are composited over the
// backdrop colors: the base color and each of the three orbs at its own alpha (the worst bright spots).
// Normal text needs 4.5:1; UI components (the focus ring) need 3:1.

type Rgb = [number, number, number];
type Rgba = [number, number, number, number];

const css = readFileSync(resolve(import.meta.dirname, "tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function parseRules(source: string): Map<string, Map<string, string>> {
  const rules = new Map<string, Map<string, string>>();
  for (const match of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = (match[1] ?? "").trim().replace(/\s+/g, " ");
    const decls = rules.get(selector) ?? new Map<string, string>();
    for (const decl of (match[2] ?? "").split(";")) {
      const at = decl.indexOf(":");
      if (at > 0) decls.set(decl.slice(0, at).trim(), decl.slice(at + 1).trim());
    }
    rules.set(selector, decls);
  }
  return rules;
}

const rules = parseRules(css);

type Vars = Map<string, string>;

function layer(base: Vars, selectors: string[]): Vars {
  const out = new Map(base);
  for (const selector of selectors) for (const [k, v] of rules.get(selector) ?? []) out.set(k, v);
  return out;
}

const dark = layer(new Map(), [":root"]);
const light = layer(dark, [':root[data-theme="light"]']);
const MODES: Record<string, Vars> = {
  dark,
  light,
  "high contrast dark": layer(dark, [':root[data-contrast="high"]']),
  "high contrast light": layer(light, [':root[data-contrast="high"][data-theme="light"]']),
};

function color(vars: Vars, name: string): Rgba {
  const raw = vars.get(name);
  if (raw === undefined) throw new Error(`token ${name} is not defined`);
  return parseColor(raw);
}

function parseColor(raw: string): Rgba {
  const value = raw.trim().toLowerCase();
  if (value === "transparent") return [0, 0, 0, 0];
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(value);
  if (hex?.[1]) {
    const h = hex[1].length === 3 ? hex[1].split("").map((c) => c + c).join("") : hex[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1];
  }
  const fn = /^rgb\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*(?:\/\s*([0-9.]+))?\s*\)$/.exec(value);
  if (fn) return [Number(fn[1]), Number(fn[2]), Number(fn[3]), fn[4] === undefined ? 1 : Number(fn[4])];
  const triplet = /^(\d+)\s+(\d+)\s+(\d+)$/.exec(value);
  if (triplet) return [Number(triplet[1]), Number(triplet[2]), Number(triplet[3]), 1];
  throw new Error(`cannot parse color "${raw}"`);
}

function over(top: Rgba, bottom: Rgb): Rgb {
  const a = top[3];
  return [0, 1, 2].map((i) => (top[i] ?? 0) * a + (bottom[i] ?? 0) * (1 - a)) as Rgb;
}

function luminance([r, g, b]: Rgb): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The backdrops a surface can sit on: the base color and each orb tinted at its own alpha. */
function backdrops(vars: Vars): [string, Rgb][] {
  const base = color(vars, "--cc-bgc");
  const rgb: Rgb = [base[0], base[1], base[2]];
  const out: [string, Rgb][] = [["backdrop", rgb]];
  const orbs = vars.get("--cc-orbs") ?? "";
  [...orbs.matchAll(/rgb\((\d+) (\d+) (\d+)\/([0-9.]+)\)/g)].forEach((m, i) => {
    const alpha = Number(m[4]);
    out.push([`orb ${String(i + 1)}`, over([Number(m[1]), Number(m[2]), Number(m[3]), alpha], rgb)]);
  });
  return out;
}

interface Row {
  pair: string;
  fg: string;
  bg: string;
  ratio: number;
  min: number;
}

function check(vars: Vars): Row[] {
  const rows: Row[] = [];
  const add = (pair: string, fg: Rgb, bg: Rgb, min = 4.5) => {
    rows.push({ pair, fg: hex(fg), bg: hex(bg), ratio: ratio(fg, bg), min });
  };
  const solid = (name: string): Rgb => {
    const c = color(vars, name);
    return [c[0], c[1], c[2]];
  };
  const texts = ["--cc-text", "--cc-text2", "--cc-text3"] as const;

  for (const [where, back] of backdrops(vars)) {
    const glass = over(color(vars, "--cc-glass"), back);
    const scrimmed = over(color(vars, "--cc-scrim"), glass);
    const chipped = over(color(vars, "--cc-chip"), scrimmed);
    const surfaces: [string, Rgb][] = [
      [where, back],
      [`glass on ${where}`, glass],
      [`scrim on glass on ${where}`, scrimmed],
    ];
    for (const [label, bg] of surfaces) {
      for (const t of texts) add(`${t} on ${label}`, solid(t), bg);
      add(`--cc-over on ${label}`, solid("--cc-over"), bg);
      add(`--cc-ice on ${label}`, solid("--cc-ice"), bg);
    }
    add(`--cc-text on chip on ${where}`, solid("--cc-text"), chipped);
    add(`--cc-text2 on chip on ${where}`, solid("--cc-text2"), chipped);
    add(`--cc-ice (focus ring) on ${where}`, solid("--cc-ice"), back, 3);
    const bar = over(color(vars, "--cc-bar"), back);
    for (const t of texts) add(`${t} on bar on ${where}`, solid(t), bar);

    for (const source of ["cal", "canvas", "ls", "gmail", "wx", "manual"]) {
      const src = color(vars, `--cc-src-${source}`);
      const tint = over([src[0], src[1], src[2], 0.1], scrimmed);
      add(`--cc-ink-${source} on its tint on ${where}`, solid(`--cc-ink-${source}`), tint);
    }
  }
  for (const t of texts) add(`${t} on pop`, solid(t), solid("--cc-pop"));
  add("--cc-on-ice on --cc-ice", solid("--cc-on-ice"), solid("--cc-ice"));
  add("--cc-on-over on --cc-over", solid("--cc-on-over"), solid("--cc-over"));
  for (let p = 1; p <= 10; p += 1) {
    add(`--cc-pill-text on --cc-p${String(p)}`, solid("--cc-pill-text"), solid(`--cc-p${String(p)}`));
  }
  return rows;
}

function hex(c: Rgb): string {
  return `#${c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
}

function table(rows: Row[]): string {
  const lines = rows.map(
    (r) => `${r.pair.padEnd(58)} ${r.fg} on ${r.bg}  ${r.ratio.toFixed(2).padStart(6)}:1  needs ${String(r.min)}`,
  );
  return `\nFailing contrast pairs:\n${lines.join("\n")}\n`;
}

// Pairs that fail because of a value in docs/design/tokens.json. Empty since T1b's four proposals were
// applied (decision 0346). The test fails on any failure, and on an entry here that starts to pass.
const FROM_TOKENS_JSON: Record<string, string> = {};

describe("WCAG contrast of used token pairs", () => {
  it.each(Object.entries(MODES))("%s", (mode, vars) => {
    const rows = check(vars);
    expect(rows.length).toBeGreaterThan(50);
    const failing = rows.filter((r) => r.ratio < r.min);
    const unexpected = failing.filter((r) => !(`${mode}|${r.pair}` in FROM_TOKENS_JSON));
    expect(unexpected.length, table(unexpected)).toBe(0);
    const failingKeys = new Set(failing.map((r) => `${mode}|${r.pair}`));
    const stale = Object.keys(FROM_TOKENS_JSON).filter((k) => k.startsWith(`${mode}|`) && !failingKeys.has(k));
    expect(stale, "listed as failing but now passing: remove from FROM_TOKENS_JSON").toEqual([]);
  });

  it("computes known ratios correctly", () => {
    expect(ratio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
    expect(ratio([119, 119, 119], [255, 255, 255])).toBeCloseTo(4.48, 1);
  });
});
