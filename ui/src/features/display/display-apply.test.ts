import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { TEXT_SCALE_RANGE } from "../../lib/display";
import { applySettings, applySourceColors, normalize } from "./display-apply";
import { DEFAULT_DOCUMENT, toDocument, type DisplayDocument } from "./display-api";
import { COLORS } from "./source-colors";
import { SOURCES } from "../../lib/sources";

const root = () => document.documentElement;

afterEach(() => {
  for (const name of [...root().getAttributeNames()].filter((n) => n.startsWith("data-") && n !== "data-theme")) {
    root().removeAttribute(name);
  }
  root().removeAttribute("data-theme");
});

describe("normalize", () => {
  it("snaps glow, text size and zoom into the ranges the server accepts", () => {
    const out = normalize({ ...DEFAULT_DOCUMENT, glow: 9, text_scale: 20, zoom: 500 });
    expect([out.glow, out.text_scale, out.zoom]).toEqual([1.6, 90, 130]);
    expect(normalize({ ...DEFAULT_DOCUMENT, zoom: 10 }).zoom).toBe(70);
    expect(normalize({ ...DEFAULT_DOCUMENT, zoom: Number.NaN }).zoom).toBe(100);
  });

  it("leaves every other key alone", () => {
    const doc: DisplayDocument = { ...DEFAULT_DOCUMENT, privacy_mode: true, owed_replies_as_tasks: true, shortcuts: false };
    expect(normalize(doc)).toEqual(doc);
  });
});

describe("applySettings", () => {
  it("writes theme, contrast, density, glow and text scale as attributes on the root", () => {
    applySettings({ ...DEFAULT_DOCUMENT, theme: "light", high_contrast: true, density: "compact", glow: 0.4, text_scale: 150 });
    expect(root()).toHaveAttribute("data-theme", "light");
    expect(root()).toHaveAttribute("data-contrast", "high");
    expect(root()).toHaveAttribute("data-density", "compact");
    expect(root()).toHaveAttribute("data-glow", "0.4");
    expect(root()).toHaveAttribute("data-text-scale", "150");
  });

  it("follows the system for the system theme and clears high contrast again", () => {
    applySettings({ ...DEFAULT_DOCUMENT, theme: "dark", high_contrast: true });
    applySettings(DEFAULT_DOCUMENT);
    expect(root()).not.toHaveAttribute("data-theme");
    expect(root()).not.toHaveAttribute("data-contrast");
  });

  it("never writes an inline style", () => {
    applySettings({ ...DEFAULT_DOCUMENT, source_colors: { gmail: "violet" }, text_scale: 150 });
    expect(root().getAttribute("style")).toBeNull();
  });
});

describe("applySourceColors", () => {
  it("sets one attribute per source that has a choice and removes the rest", () => {
    applySourceColors({ gmail: "violet", cal: "silver" });
    expect(root()).toHaveAttribute("data-src-gmail", "violet");
    expect(root()).toHaveAttribute("data-src-cal", "silver");
    expect(root()).not.toHaveAttribute("data-src-canvas");
    applySourceColors({ gmail: "teal" });
    expect(root()).toHaveAttribute("data-src-gmail", "teal");
    expect(root()).not.toHaveAttribute("data-src-cal");
    applySourceColors(undefined);
    expect(root()).not.toHaveAttribute("data-src-gmail");
  });

  it("does not apply green or pink (no tokens yet) and ignores sources it does not know", () => {
    applySourceColors({ gmail: "green", wx: "pink", other: "violet" });
    expect(root()).not.toHaveAttribute("data-src-gmail");
    expect(root()).not.toHaveAttribute("data-src-wx");
    expect(root()).not.toHaveAttribute("data-src-other");
  });

  it("has a rule in index.css for every source and every offered color", () => {
    const css = readFileSync(resolve(import.meta.dirname, "../../styles/index.css"), "utf8");
    for (const source of SOURCES) {
      for (const color of COLORS) {
        const rule = `:root[data-src-${source.id}="${color.name}"] [data-source="${source.id}"] { --cc-src: var(--cc-src-${color.token}); --cc-ink: var(--cc-ink-${color.token}); }`;
        expect(css, rule).toContain(rule);
      }
    }
    for (const color of COLORS) expect(css).toContain(`[data-swatch="${color.name}"] { --cc-src: var(--cc-src-${color.token});`);
  });
});

describe("toDocument", () => {
  it("keeps exactly the server's keys and drops revision and updated_at", () => {
    const stored = { ...DEFAULT_DOCUMENT, privacy_mode: true, revision: 4, updated_at: "2026-11-12T10:00:00Z" };
    expect(Object.keys(toDocument(stored)).sort()).toEqual(
      ["theme", "high_contrast", "density", "glow", "text_scale", "privacy_mode", "owed_replies_as_tasks", "zoom", "shortcuts"].sort(),
    );
    expect(toDocument(stored).privacy_mode).toBe(true);
  });

  it("copies source colors rather than sharing them", () => {
    const colors = { gmail: "green" } as const;
    const out = toDocument({ ...DEFAULT_DOCUMENT, source_colors: colors });
    expect(out.source_colors).toEqual({ gmail: "green" });
    expect(out.source_colors).not.toBe(colors);
  });
});

describe("the 11px caption floor", () => {
  it("holds at every text size the setting offers", () => {
    const css = readFileSync(resolve(import.meta.dirname, "../../styles/tokens.css"), "utf8");
    const match = /--cc-text-caption:\s*max\((\d+)px,\s*calc\((\d+)px \* var\(--cc-text-scale\)\)\)/.exec(css);
    expect(match).not.toBeNull();
    const floor = Number(match?.[1]);
    const base = Number(match?.[2]);
    expect(floor).toBe(11);
    for (let scale: number = TEXT_SCALE_RANGE.min; scale <= TEXT_SCALE_RANGE.max; scale += TEXT_SCALE_RANGE.step) {
      expect(Math.max(floor, (base * scale) / 100)).toBeGreaterThanOrEqual(11);
      expect(css).toContain(`:root[data-text-scale="${String(scale)}"]`);
    }
  });
});
