import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useDisplay } from "../../lib/display";
import { useTheme } from "../../lib/theme";
import { applySettings, normalize } from "./display-apply";
import { DEFAULT_DOCUMENT, fetchDisplay, replaceDisplay, toDocument, type DisplayDocument } from "./display-api";
import { DisplaySaver, FAILED_TEXT, MERGED_TEXT, SAVED_TEXT, type DisplaySaveStatus } from "./display-saver";

export const displayKey = ["display-settings"] as const;

export interface DisplaySettingsValue {
  /** What is on screen: the stored document with every change not yet saved laid over it. */
  readonly settings: DisplayDocument;
  /** Change some keys. The change shows at once, is saved after a short pause, and every other key goes back unchanged. */
  readonly update: (patch: Partial<DisplayDocument>) => void;
  readonly status: DisplaySaveStatus;
  /** One fixed sentence for `status` (empty while idle or pending); never the server's words. */
  readonly message: string;
  /** The stored document has been read at least once. */
  readonly loaded: boolean;
  /** False outside a DisplaySettingsProvider (settings stay at their defaults and nothing is saved). */
  readonly available: boolean;
}

const UNAVAILABLE: DisplaySettingsValue = {
  settings: DEFAULT_DOCUMENT,
  update: () => undefined,
  status: { kind: "idle" },
  message: "",
  loaded: false,
  available: false,
};

const DisplaySettingsContext = createContext<DisplaySettingsValue>(UNAVAILABLE);

export function messageFor(status: DisplaySaveStatus): string {
  switch (status.kind) {
    case "saved":
      return SAVED_TEXT;
    case "merged":
      return MERGED_TEXT;
    case "error":
      return FAILED_TEXT;
    default:
      return "";
  }
}

/** Owns the one saver for the app: reads GET /v1/display-settings, applies the document to the root element, and
 *  writes changes with If-Match (decision 0391). Mount it once, inside the query client and the theme and display
 *  providers; any component reads it through useDisplaySettings. */
export function DisplaySettingsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { setTheme } = useTheme();
  const { setDisplay } = useDisplay();
  const [settings, setSettings] = useState<DisplayDocument>(DEFAULT_DOCUMENT);
  const [status, setStatus] = useState<DisplaySaveStatus>({ kind: "idle" });
  const latestRef = useRef(settings);
  const setDisplayRef = useRef(setDisplay);

  const saver = useMemo(
    () =>
      new DisplaySaver({
        read: () => queryClient.query({ queryKey: displayKey, queryFn: () => fetchDisplay(), staleTime: 0 }),
        write: async (document, revision) => {
          const stored = await replaceDisplay(document, revision);
          queryClient.setQueryData(displayKey, stored);
          return stored;
        },
        onStatus: setStatus,
        onDocument: (document) => {
          setSettings(normalize(document));
        },
      }),
    [queryClient],
  );

  const query = useQuery({ queryKey: displayKey, queryFn: () => fetchDisplay() });
  const stored = query.data;
  useEffect(() => {
    if (stored) saver.adopt(stored);
  }, [stored, saver]);

  useEffect(() => {
    saver.attach();
    return () => {
      // The owner is going: the last change is still written, but nothing may reach setState afterwards.
      saver.detach();
      saver.dispose();
      void saver.flush();
    };
  }, [saver]);

  useEffect(() => {
    setDisplayRef.current = setDisplay;
  });
  useEffect(() => {
    latestRef.current = settings;
  }, [settings]);
  useEffect(() => {
    applySettings(settings);
    // Keep the in-memory theme and display state (read by /today's switcher and the gallery) in step.
    setTheme(settings.theme);
    setDisplayRef.current({
      highContrast: settings.high_contrast,
      density: settings.density,
      glow: settings.glow,
      textScale: settings.text_scale,
    });
  }, [settings, setTheme]);

  const update = useCallback(
    (patch: Partial<DisplayDocument>) => {
      const next = normalize({ ...latestRef.current, ...patch });
      const clean: Partial<DisplayDocument> = {};
      for (const key of Object.keys(patch) as (keyof DisplayDocument)[]) Object.assign(clean, { [key]: next[key] });
      latestRef.current = toDocument(next);
      setSettings(latestRef.current);
      saver.change(clean);
    },
    [saver, latestRef],
  );

  const value = useMemo<DisplaySettingsValue>(
    () => ({ settings, update, status, message: messageFor(status), loaded: stored !== undefined, available: true }),
    [settings, update, status, stored],
  );
  return <DisplaySettingsContext value={value}>{children}</DisplaySettingsContext>;
}

/** The display settings, persisted through /v1/display-settings. The app shell's Privacy toggle uses this same
 *  hook: `update({ privacy_mode: true })`. */
export function useDisplaySettings(): DisplaySettingsValue {
  return useContext(DisplaySettingsContext);
}
