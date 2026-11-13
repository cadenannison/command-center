import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type RefObject } from "react";
import { Button } from "../../components/ui/button";
import {
  DEFAULT_LAYOUTS,
  ZOOM_MAX,
  ZOOM_MIN,
  canRedo,
  canUndo,
  columnsForWidth,
  fitToColumns,
  historyReducer,
  initHistory,
  sanitizeLayout,
  type Layout,
} from "../../layout";
import { DashboardGrid } from "./dashboard-grid";
import { SummaryCard } from "./summary-card";
import { replaceDashboard } from "./dashboards-api";
import { LayoutSaver, type SaveStatus } from "./layout-saver";
import { dashboardsKey } from "./use-dashboards";
import type { Dashboard } from "./wire";

export interface DashboardViewProps {
  readonly dashboard: Dashboard;
  /** The page calls this before it switches away; it resolves false when a change could not be saved. */
  readonly flushRef: RefObject<(() => Promise<boolean>) | null>;
  /** Another tab or window saved first: the page refetches and remounts this view. Resolves false if the refetch failed. */
  readonly onConflict: () => Promise<boolean>;
  /** Called when a save succeeds, so the page can drop a stale "not saved" alert. */
  readonly onSaved?: () => void;
}

function initialLayout(dashboard: Dashboard): {
  layout: Layout;
  unreadable: boolean;
} {
  const result = sanitizeLayout(dashboard.layout);
  return result.ok ? { layout: result.layout, unreadable: false } : { layout: DEFAULT_LAYOUTS.main, unreadable: true };
}

const SAVE_TEXT: Record<SaveStatus["kind"], string> = {
  idle: "",
  pending: "Unsaved changes",
  saving: "Saving…",
  saved: "Saved",
  conflict: "",
  error: "",
};

export function DashboardView({ dashboard, flushRef, onConflict, onSaved }: DashboardViewProps) {
  const queryClient = useQueryClient();
  const start = useMemo(() => initialLayout(dashboard), [dashboard]);
  const [history, dispatch] = useReducer(historyReducer, start.layout, (layout) => initHistory(layout));
  const [edit, setEdit] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [cols, setCols] = useState<number>(() => columnsForWidth(window.innerWidth));
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [reloadFailed, setReloadFailed] = useState(false);
  const [announcement, setAnnouncement] = useState({ text: "", n: 0 });

  const dashboardId = dashboard.id;
  const dashboardName = dashboard.name;
  const [saver] = useState(
    () =>
      new LayoutSaver(dashboard.revision, {
        onStatus: setStatus,
        send: async (layout, revision) => {
          const saved = await replaceDashboard(dashboardId, revision, dashboardName, layout);
          queryClient.setQueryData<Dashboard[]>(dashboardsKey, (old) =>
            old?.map((d) => (d.id === saved.id ? saved : d)),
          );
          return saved.revision;
        },
      }),
  );
  const lastQueued = useRef<Layout>(history.present);

  useEffect(() => {
    if (history.present === lastQueued.current) return;
    lastQueued.current = history.present;
    saver.schedule(history.present);
  }, [history.present, saver]);

  useEffect(
    () => () => {
      saver.dispose();
    },
    [saver],
  );

  useEffect(() => {
    flushRef.current = async () => {
      await saver.flush();
      return !saver.failed;
    };
    return () => {
      flushRef.current = null;
    };
  }, [flushRef, saver]);

  useEffect(() => {
    if (status.kind === "saved") onSaved?.();
  }, [status.kind, onSaved]);

  const conflicted = status.kind === "conflict";
  useEffect(() => {
    if (!conflicted) return;
    let cancelled = false;
    void onConflict().then((ok) => {
      if (!cancelled) setReloadFailed(!ok);
    });
    return () => {
      cancelled = true;
    };
  }, [conflicted, onConflict]);

  const announce = useCallback((text: string) => {
    setAnnouncement((old) => ({ text, n: old.n + 1 }));
  }, []);
  const onChange = useCallback((layout: Layout) => {
    dispatch({ type: "apply", layout });
  }, []);

  const toggleEdit = () => {
    if (edit) void saver.flush();
    setEdit(!edit);
    announce(edit ? "Edit mode off." : "Edit mode on. Move to a widget header and press Enter to pick it up.");
  };

  const shown = useMemo(() => fitToColumns(history.present, cols), [history.present, cols]);
  const readOnly = cols !== 12;

  // Narrowing mid pick-up unmounts the handle that had focus, which would drop it to <body>. After the grid has
  // announced it, focus goes to the read-only notice once that notice exists (decision 0374).
  const refocusReadonly = useRef(false);
  const onPickupAbandoned = useCallback(() => {
    refocusReadonly.current = true;
  }, []);
  useEffect(() => {
    if (!readOnly || !refocusReadonly.current) return;
    refocusReadonly.current = false;
    document.getElementById("dashboard-readonly")?.focus();
  }, [readOnly]);
  const savedText = SAVE_TEXT[status.kind];

  return (
    <section aria-label={`${dashboard.name} dashboard`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={edit ? "default" : "outline"}
          aria-pressed={edit}
          disabled={readOnly}
          aria-describedby={readOnly ? "dashboard-readonly" : undefined}
          onClick={toggleEdit}
        >
          Edit
        </Button>
        {edit && !readOnly && (
          <>
            <Button
              variant="outline"
              disabled={!canUndo(history)}
              onClick={() => {
                dispatch({ type: "undo" });
              }}
            >
              Undo
            </Button>
            <Button
              variant="outline"
              disabled={!canRedo(history)}
              onClick={() => {
                dispatch({ type: "redo" });
              }}
            >
              Redo
            </Button>
          </>
        )}
        <label className="flex items-center gap-2 text-caption text-muted">
          Zoom
          <input
            type="range"
            min={ZOOM_MIN}
            max={ZOOM_MAX}
            step={10}
            value={zoom}
            aria-valuetext={`${String(zoom)} percent`}
            onChange={(event) => {
              setZoom(Number(event.target.value));
            }}
          />
          <span className="tnum w-10">{`${String(zoom)}%`}</span>
        </label>
        <span role="status" className="text-caption text-muted" data-testid="save-status">
          {savedText}
        </span>
      </div>

      {readOnly && (
        <p id="dashboard-readonly" role="status" tabIndex={-1} className="text-caption text-muted">
          {`This window shows ${String(cols)} columns, so the dashboard is read-only. Widen it to 12 columns to move or resize widgets.`}
        </p>
      )}
      {start.unreadable && (
        <p role="alert" className="text-danger">
          This dashboard&apos;s saved layout could not be read, so the default layout is shown. Changing it replaces the
          saved one.
        </p>
      )}
      {status.kind === "error" && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-danger">
          <span>{`Your last change was not saved. ${status.message}`}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void saver.retry();
            }}
          >
            Retry
          </Button>
        </div>
      )}
      {conflicted && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-danger">
          <span>
            {reloadFailed
              ? "This dashboard was changed somewhere else and the latest version could not be loaded."
              : "This dashboard was changed somewhere else. Loading the latest version; your last change was not saved."}
          </span>
          {reloadFailed && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setReloadFailed(false);
                void onConflict().then((ok) => {
                  setReloadFailed(!ok);
                });
              }}
            >
              Reload
            </Button>
          )}
        </div>
      )}

      {/* Pinned above the grid, not a grid widget (decision 0381). Kept in edit mode; it takes no focus. */}
      <SummaryCard cols={cols >= 12 ? 12 : cols >= 8 ? 8 : 4} />

      <DashboardGrid
        layout={shown}
        zoom={zoom}
        edit={edit}
        onChange={onChange}
        onAnnounce={announce}
        onColumns={setCols}
        onPickupAbandoned={onPickupAbandoned}
      />

      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only" data-testid="live-region">
        {announcement.text + (announcement.n % 2 === 0 ? "" : " ")}
      </div>
    </section>
  );
}
