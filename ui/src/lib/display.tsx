import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** Display settings (task T1, decision 0340). Each one is an attribute on <html> that tokens.css reads, so
 *  no inline style is needed (decision 0301). Like the theme (0322) they live in memory only: localStorage
 *  is banned and persisting them needs its own decision. */
export type Density = "comfortable" | "compact";

export interface DisplaySettings {
  /** High contrast: opaque surfaces, no blur, stronger hairlines. */
  highContrast: boolean;
  density: Density;
  /** Glow intensity, 0 to 1.6 in steps of 0.1. */
  glow: number;
  /** Text scale in percent, 90 to 150 in steps of 5 (decision 0335: 90, not the spec's 85). */
  textScale: number;
}

export const DEFAULT_DISPLAY: DisplaySettings = { highContrast: false, density: "comfortable", glow: 1, textScale: 100 };

export const GLOW_RANGE = { min: 0, max: 1.6, step: 0.1 } as const;
export const TEXT_SCALE_RANGE = { min: 90, max: 150, step: 5 } as const;

/** Snap a glow value into range and onto the 0.1 grid tokens.css has a rule for. NaN gives the default. */
export function clampGlow(value: number): number {
  if (Number.isNaN(value)) return DEFAULT_DISPLAY.glow;
  const stepped = Math.round(value / GLOW_RANGE.step) * GLOW_RANGE.step;
  return Math.min(GLOW_RANGE.max, Math.max(GLOW_RANGE.min, Number(stepped.toFixed(1))));
}

/** Snap a text scale into 90 to 150 on the 5 percent grid. NaN gives the default. */
export function clampTextScale(value: number): number {
  if (Number.isNaN(value)) return DEFAULT_DISPLAY.textScale;
  const stepped = Math.round(value / TEXT_SCALE_RANGE.step) * TEXT_SCALE_RANGE.step;
  return Math.min(TEXT_SCALE_RANGE.max, Math.max(TEXT_SCALE_RANGE.min, stepped));
}

export function applyDisplay(settings: DisplaySettings, root: HTMLElement = document.documentElement): void {
  if (settings.highContrast) root.setAttribute("data-contrast", "high");
  else root.removeAttribute("data-contrast");
  root.setAttribute("data-density", settings.density);
  root.setAttribute("data-glow", String(clampGlow(settings.glow)));
  root.setAttribute("data-text-scale", String(clampTextScale(settings.textScale)));
}

interface DisplayValue {
  display: DisplaySettings;
  setDisplay: (patch: Partial<DisplaySettings>) => void;
}

const DisplayContext = createContext<DisplayValue | null>(null);

export function DisplayProvider({ children, initial }: { children: ReactNode; initial?: Partial<DisplaySettings> }) {
  const [display, setState] = useState<DisplaySettings>({ ...DEFAULT_DISPLAY, ...initial });
  useEffect(() => {
    applyDisplay(display);
  }, [display]);
  const value = useMemo<DisplayValue>(
    () => ({
      display,
      setDisplay: (patch) => {
        setState((current) => ({ ...current, ...patch }));
      },
    }),
    [display],
  );
  return <DisplayContext value={value}>{children}</DisplayContext>;
}

export function useDisplay(): DisplayValue {
  const value = useContext(DisplayContext);
  if (!value) throw new Error("useDisplay needs a DisplayProvider");
  return value;
}
