import { SlidersHorizontal } from "lucide-react";
import { Popover } from "radix-ui";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Button } from "../../components/ui/button";
import { ZOOM_MAX, ZOOM_MIN } from "../../layout";
import { GLOW_RANGE, TEXT_SCALE_RANGE, clampGlow, clampTextScale } from "../../lib/display";
import { SOURCES } from "../../lib/sources";
import type { DisplayDocument, SourceColorName } from "./display-api";
import { useDisplaySettings } from "./display-settings";
import { COLORS, COLOR_NAMES, colorOf, contrastMode, contrastText } from "./source-colors";

const THEMES = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
] as const;

const DENSITIES = [
  { value: "comfortable", label: "Comfortable" },
  { value: "compact", label: "Compact" },
] as const;

export const ZOOM_STEP = 10;

const CHOICE = "inline-flex min-h-8 items-center gap-2";
const GROUP = "m-0 flex flex-col gap-1 border-0 p-0";
const LEGEND = "mb-1 p-0 text-caption font-medium text-muted";

function useMedia(query: string): boolean {
  const read = () => (typeof globalThis.matchMedia === "function" ? globalThis.matchMedia(query).matches : false);
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    if (typeof globalThis.matchMedia !== "function") return;
    const list = globalThis.matchMedia(query);
    const listener = () => {
      setMatches(list.matches);
    };
    listener();
    list.addEventListener("change", listener);
    return () => {
      list.removeEventListener("change", listener);
    };
  }, [query]);
  return matches;
}

export interface DisplayMenuProps {
  /** Where the popover is portaled: inside the page's <main>, so it is never outside every landmark (decision 0383). */
  readonly container?: HTMLElement | null;
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-1">{children}</div>;
}

/** The Display settings control: a non-modal popover opened from a header button. Every key it changes is saved
 *  through useDisplaySettings; the key it does not show (privacy_mode, owed_replies_as_tasks) is left alone. */
export function DisplayMenu({ container }: DisplayMenuProps) {
  const { settings, update, message, status, available } = useDisplaySettings();
  const ids = useId();
  const [announcement, setAnnouncement] = useState({ text: "", n: 0 });
  const systemLight = useMedia("(prefers-color-scheme: light)");
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const mode = contrastMode(settings.theme, settings.high_contrast, systemLight);

  const change = (patch: Partial<DisplayDocument>, text: string) => {
    update(patch);
    setAnnouncement((old) => ({ text, n: old.n + 1 }));
  };

  return (
    <Popover.Root modal={false}>
      <Popover.Trigger asChild>
        <Button variant="outline">
          <SlidersHorizontal size={16} aria-hidden="true" />
          Display
        </Button>
      </Popover.Trigger>
      <Popover.Portal container={container ?? null}>
        <Popover.Content
          aria-label="Display settings"
          align="start"
          sideOffset={6}
          collisionPadding={8}
          className="z-50 flex max-h-[min(80vh,42rem)] w-[min(26rem,calc(100vw-1rem))] flex-col gap-4 overflow-y-auto overflow-x-hidden rounded-control border border-edge bg-pop p-4 text-fg"
        >
          {!available && (
            <p className="m-0 text-caption text-muted">Display settings are not available on this page.</p>
          )}

          <fieldset className={GROUP}>
            <legend className={LEGEND}>Theme</legend>
            <div className="flex flex-wrap gap-x-4">
              {THEMES.map((t) => (
                <label key={t.value} className={CHOICE}>
                  <input
                    type="radio"
                    name={`${ids}-theme`}
                    className="accent-accent"
                    checked={settings.theme === t.value}
                    onChange={() => {
                      change({ theme: t.value }, `Theme: ${t.label}.`);
                    }}
                  />
                  {t.label}
                </label>
              ))}
            </div>
          </fieldset>

          <Row>
            <label htmlFor={`${ids}-zoom`} className="flex items-baseline justify-between gap-2">
              <span className="text-caption font-medium text-muted">Zoom</span>
              <span className="tnum">{`${String(settings.zoom)}%`}</span>
            </label>
            <input
              id={`${ids}-zoom`}
              type="range"
              min={ZOOM_MIN}
              max={ZOOM_MAX}
              step={ZOOM_STEP}
              value={settings.zoom}
              aria-valuetext={`${String(settings.zoom)} percent`}
              className="accent-accent"
              onChange={(event) => {
                const zoom = event.target.valueAsNumber;
                change({ zoom }, `Zoom: ${String(zoom)} percent.`);
              }}
            />
          </Row>

          <Row>
            <label htmlFor={`${ids}-text`} className="flex items-baseline justify-between gap-2">
              <span className="text-caption font-medium text-muted">Text size</span>
              <span className="tnum">{`${String(settings.text_scale)}%`}</span>
            </label>
            <input
              id={`${ids}-text`}
              type="range"
              min={TEXT_SCALE_RANGE.min}
              max={TEXT_SCALE_RANGE.max}
              step={TEXT_SCALE_RANGE.step}
              value={settings.text_scale}
              aria-valuetext={`${String(settings.text_scale)} percent`}
              className="accent-accent"
              onChange={(event) => {
                const scale = clampTextScale(event.target.valueAsNumber);
                change({ text_scale: scale }, `Text size: ${String(scale)} percent.`);
              }}
            />
          </Row>

          <fieldset className={GROUP}>
            <legend className={LEGEND}>Density</legend>
            <div className="flex flex-wrap gap-x-4">
              {DENSITIES.map((d) => (
                <label key={d.value} className={CHOICE}>
                  <input
                    type="radio"
                    name={`${ids}-density`}
                    className="accent-accent"
                    checked={settings.density === d.value}
                    onChange={() => {
                      change({ density: d.value }, `Density: ${d.label}.`);
                    }}
                  />
                  {d.label}
                </label>
              ))}
            </div>
          </fieldset>

          <Row>
            <label htmlFor={`${ids}-glow`} className="flex items-baseline justify-between gap-2">
              <span className="text-caption font-medium text-muted">Glow</span>
              <span className="tnum">{settings.glow.toFixed(1)}</span>
            </label>
            <input
              id={`${ids}-glow`}
              type="range"
              min={GLOW_RANGE.min}
              max={GLOW_RANGE.max}
              step={GLOW_RANGE.step}
              value={settings.glow}
              aria-valuetext={`${settings.glow.toFixed(1)} of ${String(GLOW_RANGE.max)}`}
              className="accent-accent"
              onChange={(event) => {
                const glow = clampGlow(event.target.valueAsNumber);
                change({ glow }, `Glow: ${glow.toFixed(1)}.`);
              }}
            />
          </Row>

          <label className={CHOICE}>
            <input
              type="checkbox"
              className="accent-accent"
              checked={settings.high_contrast}
              onChange={(event) => {
                change({ high_contrast: event.target.checked }, `High contrast ${event.target.checked ? "on" : "off"}.`);
              }}
            />
            High contrast
          </label>

          <label className={CHOICE}>
            <input
              type="checkbox"
              className="accent-accent"
              checked={settings.shortcuts}
              onChange={(event) => {
                change({ shortcuts: event.target.checked }, `Keyboard shortcuts ${event.target.checked ? "on" : "off"}.`);
              }}
            />
            Keyboard shortcuts
          </label>

          <p className="m-0 text-caption text-muted" data-testid="reduced-motion">
            {`Reduced motion follows your system setting. It is currently ${reduced ? "on, so animation is off" : "off"}.`}
          </p>

          <fieldset className={GROUP}>
            <legend className={LEGEND}>Source colors</legend>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {SOURCES.map((source) => {
                const color = colorOf(settings, source.id);
                const resultId = `${ids}-result-${source.id}`;
                return (
                  <li key={source.id} className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <label htmlFor={`${ids}-color-${source.id}`} className="min-w-0 flex-1">
                        {source.name}
                      </label>
                      <span
                        data-swatch={color}
                        aria-hidden="true"
                        className="inline-flex min-h-6 items-center gap-1 rounded-chip bg-[rgb(var(--cc-src)/0.1)] px-2 text-caption text-[var(--cc-ink)]"
                      >
                        <span className="inline-block size-2.5 rounded-full bg-[rgb(var(--cc-src))]" />
                        Aa
                      </span>
                      <select
                        id={`${ids}-color-${source.id}`}
                        aria-describedby={resultId}
                        value={color}
                        className="min-h-8 rounded-control border border-line2 bg-chip px-2 text-fg"
                        onChange={(event) => {
                          const chosen = COLOR_NAMES.find((n) => n === event.target.value);
                          if (!chosen) return;
                          const label = COLORS.find((c) => c.name === chosen)?.label ?? chosen;
                          const next: Record<string, SourceColorName> = { ...settings.source_colors, [source.id]: chosen };
                          change({ source_colors: next }, `${source.name} color: ${label}.`);
                        }}
                      >
                        {COLORS.map((c) => (
                          <option key={c.name} value={c.name}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <span id={resultId} className="text-caption text-muted">
                      {`Contrast ${contrastText(color, mode)}`}
                    </span>
                  </li>
                );
              })}
            </ul>
          </fieldset>

          <p role="status" className="m-0 min-h-4 text-caption text-muted" data-testid="display-save-status">
            {status.kind === "error" ? "" : message}
          </p>
          {status.kind === "error" && (
            <p role="alert" className="m-0 text-danger">
              {message}
            </p>
          )}

          <div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="display-live-region">
            {announcement.text + (announcement.n % 2 === 0 ? "" : " ")}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
