import { clampZoom } from "../../layout";
import { applyTheme } from "../../lib/theme";
import { applyDisplay, clampGlow, clampTextScale } from "../../lib/display";
import { SOURCES } from "../../lib/sources";
import { COLOR_NAMES } from "./source-colors";
import type { DisplayDocument } from "./display-api";

/** Snap every numeric key into the range the server accepts, so a stored or typed value can never reach the page raw. */
export function normalize(document: DisplayDocument): DisplayDocument {
  return {
    ...document,
    glow: clampGlow(document.glow),
    text_scale: clampTextScale(document.text_scale),
    zoom: clampZoom(document.zoom),
  };
}

/** Source colors are attributes on the root (`data-src-gmail="violet"`); index.css has one rule per pair, so the
 *  choice needs no inline style (decision 0301) and two sources can swap colors without a variable cycle. A
 *  name this UI does not offer (green, pink: decision 0390) is kept in the document but not applied. */
export function applySourceColors(colors: DisplayDocument["source_colors"], root: HTMLElement = document.documentElement): void {
  for (const source of SOURCES) {
    const choice = colors?.[source.id];
    const known = choice !== undefined && (COLOR_NAMES as readonly string[]).includes(choice);
    if (known) root.setAttribute(`data-src-${source.id}`, choice);
    else root.removeAttribute(`data-src-${source.id}`);
  }
}

/** Write what the root element carries: theme, contrast, density, glow, text scale and source colors. Zoom and the
 *  shortcuts switch are read by the grid and the dashboard, not by CSS. */
export function applySettings(document: DisplayDocument, root: HTMLElement = globalThis.document.documentElement): void {
  const settings = normalize(document);
  applyTheme(settings.theme, root);
  applyDisplay(
    { highContrast: settings.high_contrast, density: settings.density, glow: settings.glow, textScale: settings.text_scale },
    root,
  );
  applySourceColors(settings.source_colors, root);
}
