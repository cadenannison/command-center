import type { SourceId } from "../../lib/sources";
import type { DisplayDocument } from "./display-api";

/** The six colors docs/design/tokens.json defines, in the order of the spec's list. Each is the token of one source
 *  (violet is `cal`, rose `canvas`, and so on). The spec names eight; green and pink need tokens designed first
 *  (decision 0390), so they are not offered. */
export const COLORS = [
  { name: "violet", label: "Violet", token: "cal" },
  { name: "rose", label: "Rose", token: "canvas" },
  { name: "teal", label: "Teal", token: "ls" },
  { name: "amber", label: "Amber", token: "gmail" },
  { name: "sky", label: "Sky", token: "wx" },
  { name: "silver", label: "Silver", token: "manual" },
] as const;

export type OfferedColor = (typeof COLORS)[number]["name"];

export const COLOR_NAMES: readonly OfferedColor[] = COLORS.map((c) => c.name);

/** The default color of each source: Calendar violet, Canvas rose, LearningSuite teal, Gmail amber, Weather sky,
 *  My tasks silver (spec, Tokens). */
export const DEFAULT_COLOR: Record<SourceId, OfferedColor> = {
  cal: "violet",
  canvas: "rose",
  ls: "teal",
  gmail: "amber",
  wx: "sky",
  manual: "silver",
};

export type ContrastMode = "dark" | "light" | "high-dark" | "high-light";

/** The lowest contrast of a color's label ink on its own tint, over the glass surface and every backdrop spot, in
 *  each mode. The test source-colors.test.ts recomputes every value from tokens.css, so this table cannot drift. */
export const INK_CONTRAST: Record<OfferedColor, Record<ContrastMode, number>> = {
  violet: { dark: 6.7, light: 6.0, "high-dark": 7.8, "high-light": 6.5 },
  rose: { dark: 7.1, light: 5.1, "high-dark": 8.2, "high-light": 5.6 },
  teal: { dark: 9.1, light: 4.9, "high-dark": 10.7, "high-light": 5.3 },
  amber: { dark: 9.0, light: 5.2, "high-dark": 10.5, "high-light": 5.7 },
  sky: { dark: 8.6, light: 4.9, "high-dark": 10.1, "high-light": 5.4 },
  silver: { dark: 8.4, light: 6.1, "high-dark": 9.9, "high-light": 6.7 },
};

/** WCAG AA for normal text. */
export const AA = 4.5;

export function contrastMode(theme: DisplayDocument["theme"], highContrast: boolean, systemLight: boolean): ContrastMode {
  const light = theme === "light" || (theme === "system" && systemLight);
  if (highContrast) return light ? "high-light" : "high-dark";
  return light ? "light" : "dark";
}

export function colorOf(settings: DisplayDocument, source: SourceId): OfferedColor {
  const chosen = settings.source_colors?.[source];
  return COLOR_NAMES.find((name) => name === chosen) ?? DEFAULT_COLOR[source];
}

/** Every choice the UI offers is AA in every mode, so the result reads "AA"; the number is shown beside it. */
export function contrastText(color: OfferedColor, mode: ContrastMode): string {
  const ratio = INK_CONTRAST[color][mode];
  return `${ratio.toFixed(1)}:1, ${ratio >= AA ? "passes AA" : "fails AA"}`;
}
