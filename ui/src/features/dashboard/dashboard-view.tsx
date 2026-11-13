import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type RefObject } from "react";
import { Button } from "../../components/ui/button";
import {
  DEFAULT_LAYOUTS,
  ZOOM_MAX,
  ZOOM_MIN,
  addWidget,
  canRedo,
  canUndo,
  columnsForWidth,
  fitToColumns,
  historyReducer,
  getWidget,
  initHistory,
  preset,
  remove,
  resize,
  sanitizeLayout,
  setPinned,
  type Layout,
  type LayoutItem,
  type SizePreset,
  type TemplateName,
} from "../../layout";
import { DashboardGrid } from "./dashboard-grid";
import { downloadText } from "./download";
import { EditToolbar } from "./edit-toolbar";
import { addBlocker, exportDocument, nextItemId, presetState, sizeText } from "./edit-model";
import { WidgetMenu } from "./widget-menu";
import { layoutToWire } from "./wire";
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

  // Dialogs hide the rest of the page from assistive technology while open, live region included, so what
  // they cause is announced a moment after they close.
  const announceLater = useCallback(
    (text: string) => {
      setTimeout(() => {
        announce(text);
      }, 100);
    },
    [announce],
  );

  // Focus that must land after a control unmounted (Done, or a removed widget's menu). Set in a handler, applied after
  // the commit and after Radix has finished returning focus to a trigger that no longer exists.
  // The widget menus portal into this section, which sits inside the page's <main> (router.tsx).
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const focusNext = useRef<"edit" | "add" | null>(null);
  useEffect(() => {
    const target = focusNext.current;
    if (!target) return;
    focusNext.current = null;
    setTimeout(() => {
      (target === "edit" ? editRef : addRef).current?.focus();
    }, 0);
  });

  const toggleEdit = () => {
    if (edit) void saver.flush();
    setEdit(!edit);
    announce(edit ? "Edit mode off." : "Edit mode on. Move to a widget header and press Enter to pick it up.");
  };
  const done = () => {
    focusNext.current = "edit";
    toggleEdit();
  };

  const titleOf = (item: LayoutItem): string => getWidget(item.widgetId)?.title ?? item.widgetId;
  const where = (item: LayoutItem): string =>
    `column ${String(item.x + 1)}, row ${String(item.y + 1)}, ${String(item.w)} wide, ${String(item.h)} tall`;

  const onAdd = (widgetId: string) => {
    const layout = history.present;
    const name = getWidget(widgetId)?.title ?? widgetId;
    const blocker = addBlocker(layout, widgetId);
    if (blocker) {
      announceLater(`${name} was not added. ${blocker}`);
      return;
    }
    const id = nextItemId(layout, widgetId);
    const next = addWidget(layout, widgetId, id, 12);
    const added = next.items.find((i) => i.id === id);
    if (!added) {
      announceLater(`${name} was not added.`);
      return;
    }
    dispatch({ type: "apply", layout: next });
    announceLater(`Added ${name} at ${where(added)}.`);
  };
  const onUndo = () => {
    dispatch({ type: "undo" });
    announce("Undone.");
  };
  const onRedo = () => {
    dispatch({ type: "redo" });
    announce("Redone.");
  };
  const onReset = (template: TemplateName, label: string) => {
    const layout = DEFAULT_LAYOUTS[template];
    if (JSON.stringify(layoutToWire(layout)) === JSON.stringify(layoutToWire(history.present))) {
      announceLater(`The layout already matches the ${label} template.`);
      return;
    }
    dispatch({ type: "apply", layout });
    announceLater(`Applied the ${label} template: ${String(layout.items.length)} widgets. Undo brings the previous layout back.`);
  };
  const onExport = () => {
    const file = exportDocument(dashboardName, history.present);
    downloadText(file.filename, file.content);
    announce(`Exported ${file.filename}.`);
  };
  const itemMenu = (item: LayoutItem) => (
    <WidgetMenu
      item={item}
      title={titleOf(item)}
      container={portalRoot}
      onRemove={() => {
        focusNext.current = "add";
        dispatch({ type: "apply", layout: remove(history.present, item.id) });
        announce(`${titleOf(item)} removed. Undo brings it back.`);
      }}
      onSize={(name: SizePreset) => {
        const state = presetState(item, name);
        if (state.disabled) {
          announce(`${titleOf(item)} cannot be resized: ${state.reason ?? ""}`);
          return;
        }
        const def = getWidget(item.widgetId);
        const size = def ? preset(name, def) : state.size;
        const next = resize(history.present, item.id, size.w, size.h, 12);
        dispatch({ type: "apply", layout: next });
        const after = next.items.find((i) => i.id === item.id);
        announce(`${titleOf(item)} resized to ${sizeText(after ?? size)}.`);
      }}
      onPin={(pinned) => {
        dispatch({ type: "apply", layout: setPinned(history.present, item.id, pinned) });
        announce(
          pinned
            ? `${titleOf(item)} pinned. It cannot be moved or resized.`
            : `${titleOf(item)} unpinned. It can be moved and resized again.`,
        );
      }}
    />
  );

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
    <section ref={setPortalRoot} aria-label={`${dashboard.name} dashboard`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          ref={editRef}
          variant={edit ? "default" : "outline"}
          aria-pressed={edit}
          disabled={readOnly}
          aria-describedby={readOnly ? "dashboard-readonly" : undefined}
          onClick={toggleEdit}
        >
          Edit
        </Button>
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

      {edit && !readOnly && (
        <EditToolbar
          layout={history.present}
          dashboardName={dashboardName}
          canUndo={canUndo(history)}
          canRedo={canRedo(history)}
          onAdd={onAdd}
          onUndo={onUndo}
          onRedo={onRedo}
          onReset={onReset}
          onExport={onExport}
          onDone={done}
          addRef={addRef}
        />
      )}

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
        itemMenu={itemMenu}
      />

      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only" data-testid="live-region">
        {announcement.text + (announcement.n % 2 === 0 ? "" : " ")}
      </div>
    </section>
  );
}
