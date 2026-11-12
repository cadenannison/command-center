import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Drift guard (task T1, decision 0340): every token in docs/design/tokens.json must exist in tokens.css with
// the same value, in the rule that owns it. tokens.css is written by hand; this test is what keeps it honest.
const css = readFileSync(resolve(import.meta.dirname, "tokens.css"), "utf8");
const indexCss = readFileSync(resolve(import.meta.dirname, "index.css"), "utf8");
const tokens = JSON.parse(readFileSync(resolve(import.meta.dirname, "../../../docs/design/tokens.json"), "utf8")) as Tokens;

interface Tokens {
  themes: Record<
    "dark" | "light",
    {
      color: Record<string, string>;
      glass: Record<string, string>;
      source: Record<string, string>;
      sourceInk: Record<string, string>;
      orbs: string;
    }
  >;
  highContrast: Record<"dark" | "light", Record<string, string>>;
  priority: { colors: string[]; text: string };
  text: { fontScale: { default: number } };
  shape: Record<string, string | number>;
  glow: {
    intensity: { default: number };
    ringAlpha: number;
    innerBlurPx: number;
    innerAlpha: number;
    outerBlurPx: number;
    outerAlpha: number;
  };
  density: { comfortableRow: string; compactRow: string; gapPx: number; rowUnitPx: number };
  type: { display: string; ui: string; basePx: number };
  motion: { fastMs: number; baseMs: number; checkOffMs: number; ease: string };
  grid: { zoomRange: [number, number] };
}

type Rules = Map<string, Map<string, string>>;

function parseRules(source: string): Rules {
  const rules: Rules = new Map();
  const text = source.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
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

/** Compare values ignoring case, spacing around commas and a missing leading zero (".46" and "0.46"). */
function norm(value: string): string {
  return value
    .toLowerCase()
    .replace(/\s*,\s*/g, ",")
    .replace(/(?<![0-9])\.(?=[0-9])/g, "0.")
    .replace(/\s+/g, " ")
    .trim();
}

const rules = parseRules(css);

interface Expectation {
  selectors: string[];
  name: string;
  value: string;
}

const DARK = [":root"];
const LIGHT = [':root[data-theme="light"]', ":root:not([data-theme])"];
const HC_DARK = [':root[data-contrast="high"]'];
const HC_LIGHT = [':root[data-contrast="high"][data-theme="light"]', ':root[data-contrast="high"]:not([data-theme])'];

function expectations(): Expectation[] {
  const out: Expectation[] = [];
  const themeSelectors = { dark: DARK, light: LIGHT };
  for (const theme of ["dark", "light"] as const) {
    const t = tokens.themes[theme];
    const selectors = themeSelectors[theme];
    for (const [key, value] of Object.entries(t.color)) out.push({ selectors, name: `--cc-${key}`, value });
    for (const [key, value] of Object.entries(t.glass)) out.push({ selectors, name: `--cc-${key}`, value });
    for (const [key, value] of Object.entries(t.source)) out.push({ selectors, name: `--cc-src-${key}`, value });
    for (const [key, value] of Object.entries(t.sourceInk)) out.push({ selectors, name: `--cc-ink-${key}`, value });
    out.push({ selectors, name: "--cc-orbs", value: t.orbs });
  }
  const hcSelectors = { dark: HC_DARK, light: HC_LIGHT };
  for (const theme of ["dark", "light"] as const) {
    for (const [key, value] of Object.entries(tokens.highContrast[theme])) {
      out.push({ selectors: hcSelectors[theme], name: `--cc-${key}`, value });
    }
  }
  tokens.priority.colors.forEach((value, index) => {
    out.push({ selectors: DARK, name: `--cc-p${String(index + 1)}`, value });
  });
  const g = (name: string, value: string | number) => out.push({ selectors: DARK, name, value: String(value) });
  g("--cc-pill-text", tokens.priority.text);
  g("--cc-radius-widget", tokens.shape["widgetRadius"] ?? "");
  g("--cc-radius-control", tokens.shape["controlRadius"] ?? "");
  g("--cc-radius-chip", tokens.shape["chipRadius"] ?? "");
  g("--cc-radius-pill", tokens.shape["pillRadius"] ?? "");
  g("--cc-radius-block", tokens.shape["calendarBlockRadius"] ?? "");
  g("--cc-target", `${String(tokens.shape["targetPx"])}px`);
  g("--cc-target-chip", `${String(tokens.shape["calendarChipTargetPx"])}px`);
  g("--cc-target-small", `${String(tokens.shape["smallButtonTargetPx"])}px`);
  g("--cc-glow", tokens.glow.intensity.default);
  g("--cc-glow-ring-alpha", tokens.glow.ringAlpha);
  g("--cc-glow-inner-blur", `${String(tokens.glow.innerBlurPx)}px`);
  g("--cc-glow-inner-alpha", tokens.glow.innerAlpha);
  g("--cc-glow-outer-blur", `${String(tokens.glow.outerBlurPx)}px`);
  g("--cc-glow-outer-alpha", tokens.glow.outerAlpha);
  g("--cc-row-comfortable", tokens.density.comfortableRow);
  g("--cc-row-compact", tokens.density.compactRow);
  g("--cc-gap", `${String(tokens.density.gapPx)}px`);
  g("--cc-row-unit", `${String(tokens.density.rowUnitPx)}px`);
  g("--cc-font-ui", tokens.type.ui);
  g("--cc-font-base", `${String(tokens.type.basePx)}px`);
  g("--cc-text-scale", tokens.text.fontScale.default);
  g("--cc-fast", `${String(tokens.motion.fastMs)}ms`);
  g("--cc-base", `${String(tokens.motion.baseMs)}ms`);
  g("--cc-checkoff", `${String(tokens.motion.checkOffMs)}ms`);
  g("--cc-ease", tokens.motion.ease);
  g("--cc-zoom-min", tokens.grid.zoomRange[0]);
  g("--cc-zoom-max", tokens.grid.zoomRange[1]);
  return out;
}

describe("tokens.css matches docs/design/tokens.json", () => {
  const all = expectations();

  it("checks a meaningful number of tokens", () => {
    expect(all.length).toBeGreaterThanOrEqual(100);
  });

  it.each(all.map((e) => [`${e.selectors.join(" | ")} ${e.name}`, e] as const))("%s", (_label, e) => {
    for (const selector of e.selectors) {
      const actual = rules.get(selector)?.get(e.name);
      expect(actual, `${selector} is missing ${e.name}`).toBeDefined();
      expect(norm(actual ?? "")).toBe(norm(e.value));
    }
  });

  it("uses Sora first for the display font", () => {
    expect(norm(rules.get(":root")?.get("--cc-font-display") ?? "")).toMatch(
      new RegExp(`^"${tokens.type.display.toLowerCase()}",`),
    );
  });
});

describe("display settings in tokens.css (decision 0335)", () => {
  it("has a glow rule for every 0.1 step from 0 to 1.6", () => {
    for (let tenth = 0; tenth <= 16; tenth += 1) {
      const value = String(tenth / 10);
      expect(rules.get(`:root[data-glow="${value}"]`)?.get("--cc-glow"), `glow ${value}`).toBe(value);
    }
    expect([...rules.keys()].filter((s) => s.startsWith(":root[data-glow=")).length).toBe(17);
  });

  it("has a text scale rule for every 5 percent from 90 to 150 and none outside", () => {
    for (let percent = 90; percent <= 150; percent += 5) {
      const rule = rules.get(`:root[data-text-scale="${String(percent)}"]`);
      expect(rule?.get("--cc-text-scale"), `scale ${String(percent)}`).toBe(String(percent / 100));
    }
    expect([...rules.keys()].filter((s) => s.startsWith(":root[data-text-scale=")).length).toBe(13);
  });

  it("floors captions at 11px and switches the row height for compact density", () => {
    expect(rules.get(":root")?.get("--cc-text-caption")).toMatch(/^max\(11px,/);
    expect(rules.get(':root[data-density="compact"]')?.get("--cc-row")).toBe("var(--cc-row-compact)");
  });

  it("removes blur in high contrast", () => {
    for (const selector of [...HC_DARK, ...HC_LIGHT]) expect(rules.get(selector)?.get("--cc-blur")).toBe("none");
  });
});

describe("index.css only reads tokens that exist", () => {
  it("defines every --cc-* variable it references", () => {
    const defined = new Set<string>();
    for (const decls of rules.values()) for (const name of decls.keys()) defined.add(name);
    const used = new Set([...indexCss.matchAll(/var\((--cc-[a-z0-9-]+)/g)].map((m) => m[1] ?? ""));
    // --cc-src, --cc-ink, --cc-p and --cc-glow-rgb are set by index.css rules, not tokens.css.
    const local = new Set(["--cc-src", "--cc-ink", "--cc-p", "--cc-glow-rgb"]);
    const missing = [...used].filter((name) => !defined.has(name) && !local.has(name));
    expect(missing).toEqual([]);
  });
});
