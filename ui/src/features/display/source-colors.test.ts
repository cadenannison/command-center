import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SOURCES } from "../../lib/sources";
import { AA, COLORS, COLOR_NAMES, DEFAULT_COLOR, INK_CONTRAST, colorOf, contrastMode, contrastText, type ContrastMode } from "./source-colors";
import { DEFAULT_DOCUMENT } from "./display-api";

// Recomputes, from tokens.css the way the browser cascades it, the contrast of each color choice's label ink on its
// own tint over the glass surface and every backdrop spot (the pairs contrast.test.ts checks for the default
// sources), in the four modes. INK_CONTRAST must match, and every value must be AA (decision 0390).
type Rgb = [number, number, number];
type Rgba = [number, number, number, number];
type Vars = Map<string, string>;

const css = readFileSync(resolve(import.meta.dirname, "../../styles/tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const rules = new Map<string, Vars>();
for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const selector = (match[1] ?? "").trim().replace(/\s+/g, " ");
  const decls = rules.get(selector) ?? new Map<string, string>();
  for (const decl of (match[2] ?? "").split(";")) {
    const at = decl.indexOf(":");
    if (at > 0) decls.set(decl.slice(0, at).trim(), decl.slice(at + 1).trim());
  }
  rules.set(selector, decls);
}

function layer(base: Vars, selectors: string[]): Vars {
  const out = new Map(base);
  for (const selector of selectors) for (const [k, v] of rules.get(selector) ?? []) out.set(k, v);
  return out;
}

const dark = layer(new Map(), [":root"]);
const light = layer(dark, [':root[data-theme="light"]']);
const MODES: Record<ContrastMode, Vars> = {
  dark,
  light,
  "high-dark": layer(dark, [':root[data-contrast="high"]']),
  "high-light": layer(light, [':root[data-contrast="high"][data-theme="light"]']),
};

function parse(raw: string | undefined): Rgba {
  const value = (raw ?? "").trim().toLowerCase();
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
  throw new Error(`cannot parse ${String(raw)}`);
}

const over = (top: Rgba, bottom: Rgb): Rgb =>
  [0, 1, 2].map((i) => (top[i] ?? 0) * top[3] + (bottom[i] ?? 0) * (1 - top[3])) as Rgb;

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

const solid = (vars: Vars, name: string): Rgb => {
  const c = parse(vars.get(name));
  return [c[0], c[1], c[2]];
};

/** Lowest ratio over the base backdrop and each orb, rounded down to one decimal. */
function worst(vars: Vars, token: string): number {
  const base = solid(vars, "--cc-bgc");
  const spots: Rgb[] = [base];
  for (const m of (vars.get("--cc-orbs") ?? "").matchAll(/rgb\((\d+) (\d+) (\d+)\/([0-9.]+)\)/g)) {
    spots.push(over([Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])], base));
  }
  const src = parse(vars.get(`--cc-src-${token}`));
  const ink = solid(vars, `--cc-ink-${token}`);
  const lows = spots.map((back) => {
    const glass = over(parse(vars.get("--cc-glass")), back);
    const scrimmed = over(parse(vars.get("--cc-scrim")), glass);
    return ratio(ink, over([src[0], src[1], src[2], 0.1], scrimmed));
  });
  return Math.floor(Math.min(...lows) * 10) / 10;
}

function computed(): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const color of COLORS) {
    const row: Record<string, number> = {};
    for (const [mode, vars] of Object.entries(MODES)) row[mode] = worst(vars, color.token);
    out[color.name] = row;
  }
  return out;
}

describe("source color choices", () => {
  it("offers exactly the six tokens in tokens.json, one for each default source color", () => {
    const tokens = JSON.parse(readFileSync(resolve(import.meta.dirname, "../../../../docs/design/tokens.json"), "utf8")) as {
      themes: { dark: { source: Record<string, string> } };
    };
    expect(COLORS.map((c) => c.token).sort()).toEqual(Object.keys(tokens.themes.dark.source).sort());
    expect(COLOR_NAMES).toHaveLength(6);
    expect(COLOR_NAMES).not.toContain("green");
    expect(COLOR_NAMES).not.toContain("pink");
    expect(Object.values(DEFAULT_COLOR).sort()).toEqual([...COLOR_NAMES].sort());
    expect(SOURCES.map((s) => s.id).sort()).toEqual(Object.keys(DEFAULT_COLOR).sort());
  });

  it("states the lowest contrast of each choice in each mode as tokens.css computes it", () => {
    expect(INK_CONTRAST).toEqual(computed());
  });

  it("is AA for every choice in every mode, including high contrast", () => {
    for (const color of COLORS) {
      for (const mode of Object.keys(MODES) as ContrastMode[]) {
        expect(INK_CONTRAST[color.name][mode], `${color.name} in ${mode}`).toBeGreaterThanOrEqual(AA);
      }
    }
  });

  it("picks the contrast mode from the theme, the system preference and high contrast", () => {
    expect(contrastMode("system", false, true)).toBe("light");
    expect(contrastMode("system", false, false)).toBe("dark");
    expect(contrastMode("dark", true, true)).toBe("high-dark");
    expect(contrastMode("light", true, false)).toBe("high-light");
  });

  it("reads a color, falling back to the default for a missing or not offered name", () => {
    expect(colorOf(DEFAULT_DOCUMENT, "gmail")).toBe("amber");
    expect(colorOf({ ...DEFAULT_DOCUMENT, source_colors: { gmail: "violet" } }, "gmail")).toBe("violet");
    expect(colorOf({ ...DEFAULT_DOCUMENT, source_colors: { gmail: "green" } }, "gmail")).toBe("amber");
  });

  it("words the result with the ratio and pass or fail", () => {
    expect(contrastText("violet", "dark")).toMatch(/^\d+\.\d:1, passes AA$/);
  });
});
