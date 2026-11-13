import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { getWidget, tier, type Layout, type LayoutItem } from "../../layout";
import { sourceName } from "../../components/ui/source-dot";
import { cn } from "../../lib/utils";
import {
  cancelled,
  describeChange,
  dropped,
  isArrow,
  itemOf,
  keyboardStep,
  pickedUp,
  pointerMove,
  pointerResize,
  tierLabel,
} from "./editing";
import { cellsMoved, gridHeight, metricsFor, rectOf, type Metrics } from "./metrics";
import { TasksWidget } from "./tasks-widget";
import { WidgetShell, type WidgetShellProps, type WidgetState } from "./widget-shell";
import { useGridSize } from "./use-container-width";

export const HELP_ID = "dashboard-edit-help";

type Handle = "move" | "e" | "s" | "se";

interface PointerDrag {
  readonly id: string;
  readonly handle: Handle;
  readonly pointerId: number;
  readonly startX: number;
  readonly startY: number;
  readonly base: Layout;
  readonly cellsX: number;
  readonly cellsY: number;
  readonly dx: number;
  readonly dy: number;
}

interface KeyedEdit {
  readonly id: string;
  readonly base: Layout;
  readonly current: Layout;
}

export interface DashboardGridProps {
  /** The layout as shown at the current column count (already fitted). */
  readonly layout: Layout;
  readonly zoom: number;
  /** Edit mode asked for by the user; it only takes effect at 12 columns. */
  readonly edit: boolean;
  readonly onChange: (layout: Layout) => void;
  readonly onAnnounce: (message: string) => void;
  /** Per-item body state; every widget is "ready" with a placeholder body when absent. */
  readonly stateFor?: (item: LayoutItem) => WidgetState;
  /** Reports the column count so the page can show the read-only notice. */
  readonly onColumns?: (cols: number) => void;
  /** Called after the announcement when narrowing abandoned a pick-up, so the page can move focus (decision 0374). */
  readonly onPickupAbandoned?: () => void;
}

const titleOf = (item: LayoutItem): string => getWidget(item.widgetId)?.title ?? item.widgetId;

const HANDLES: readonly {
  handle: Exclude<Handle, "move">;
  className: string;
  cursor: string;
}[] = [
  {
    handle: "e",
    className: "right-0 top-3 bottom-3 w-3",
    cursor: "cursor-ew-resize",
  },
  {
    handle: "s",
    className: "bottom-0 left-3 right-3 h-3",
    cursor: "cursor-ns-resize",
  },
  {
    handle: "se",
    className: "bottom-0 right-0 size-4",
    cursor: "cursor-nwse-resize",
  },
];

export function DashboardGrid({ layout, zoom, edit, onChange, onAnnounce, stateFor, onColumns, onPickupAbandoned }: DashboardGridProps) {
  const ref = useRef<HTMLDivElement>(null);
  const { width, cols } = useGridSize(ref);
  const editing = edit && cols === 12;
  const [drag, setDrag] = useState<PointerDrag | null>(null);
  const [keyed, setKeyed] = useState<KeyedEdit | null>(null);
  const metrics: Metrics = useMemo(() => metricsFor(width, cols, zoom), [width, cols, zoom]);

  useEffect(() => {
    onColumns?.(cols);
  }, [cols, onColumns]);

  // Leaving edit mode, or narrowing the window, abandons any pick-up that was in progress.
  const [wasEditing, setWasEditing] = useState(editing);
  if (wasEditing !== editing) {
    setWasEditing(editing);
    if (!editing) {
      setDrag(null);
      setKeyed(null);
    }
  }

  const holding = drag !== null || keyed !== null;
  const heldRef = useRef(false);
  useEffect(() => {
    if (editing) {
      heldRef.current = holding;
      return;
    }
    if (heldRef.current && edit) {
      onAnnounce("The window is too narrow to edit, so the widget you were moving was put back.");
      onPickupAbandoned?.();
    }
    heldRef.current = false;
  }, [editing, holding, edit, onAnnounce, onPickupAbandoned]);

  const preview = useMemo(() => {
    if (!drag) return null;
    return drag.handle === "move"
      ? pointerMove(drag.base, drag.id, drag.cellsX, drag.cellsY, cols)
      : pointerResize(
          drag.base,
          drag.id,
          drag.handle === "s" ? 0 : drag.cellsX,
          drag.handle === "e" ? 0 : drag.cellsY,
          cols,
        );
  }, [drag, cols]);

  const shown = preview ?? keyed?.current ?? layout;

  useEffect(() => {
    if (!drag) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const item = itemOf(drag.base, drag.id);
      setDrag(null);
      if (item) onAnnounce(cancelled(titleOf(item), item));
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [drag, onAnnounce]);

  const startPointer = (event: PointerEvent<HTMLElement>, item: LayoutItem, handle: Handle) => {
    if (!editing || event.button !== 0 || item.pinned || drag) return;
    event.preventDefault();
    if (typeof event.currentTarget.setPointerCapture === "function")
      event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({
      id: item.id,
      handle,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      base: keyed?.current ?? layout,
      cellsX: 0,
      cellsY: 0,
      dx: 0,
      dy: 0,
    });
  };

  const movePointer = (event: PointerEvent<HTMLElement>) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    const moved = cellsMoved(dx, dy, metrics);
    setDrag({ ...drag, dx, dy, cellsX: moved.dx, cellsY: moved.dy });
  };

  const endPointer = (event: PointerEvent<HTMLElement>, commit: boolean) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const el = event.currentTarget;
    if (typeof el.hasPointerCapture === "function" && el.hasPointerCapture(event.pointerId))
      el.releasePointerCapture(event.pointerId);
    const next = preview;
    const id = drag.id;
    const before = itemOf(drag.base, id);
    setDrag(null);
    if (!before) return;
    if (!commit || !next) {
      onAnnounce(cancelled(titleOf(before), before));
      return;
    }
    const after = itemOf(next, id);
    if (after) {
      onAnnounce(
        next === drag.base || JSON.stringify(next) === JSON.stringify(drag.base)
          ? `${titleOf(before)} stays at column ${String(before.x + 1)}, row ${String(before.y + 1)}.`
          : dropped(titleOf(before), after),
      );
    }
    onChange(next);
  };

  const onHeaderKey = (event: KeyboardEvent<HTMLElement>, item: LayoutItem) => {
    if (!editing || drag) return;
    const title = titleOf(item);
    const lifted = keyed?.id === item.id;
    if (!lifted) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setKeyed({ id: item.id, base: layout, current: layout });
        onAnnounce(pickedUp(title, item));
      }
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const final = keyed.current;
      setKeyed(null);
      const after = itemOf(final, item.id) ?? item;
      onAnnounce(dropped(title, after));
      onChange(final);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      const before = itemOf(keyed.base, item.id) ?? item;
      setKeyed(null);
      onAnnounce(cancelled(title, before));
    } else if (isArrow(event.key)) {
      event.preventDefault();
      const next = keyboardStep(keyed.current, item.id, event.key, event.shiftKey, cols);
      onAnnounce(describeChange(title, itemOf(keyed.current, item.id), itemOf(next, item.id), event.shiftKey));
      setKeyed({ ...keyed, current: next });
    }
  };

  // Tabbing away from a picked-up widget drops it where it is, so nothing stays half-held.
  const onHeaderBlur = (item: LayoutItem) => {
    if (keyed?.id !== item.id) return;
    const final = keyed.current;
    setKeyed(null);
    onAnnounce(dropped(titleOf(item), itemOf(final, item.id) ?? item));
    onChange(final);
  };

  const outline = drag && preview ? itemOf(preview, drag.id) : null;
  const rows = shown.items.reduce((max, i) => Math.max(max, i.y + i.h), 0);

  return (
    <div
      ref={ref}
      data-testid="dashboard-grid"
      data-cols={cols}
      data-editing={editing ? "true" : "false"}
      className="relative w-full"
      style={{ height: gridHeight(rows, metrics) }}
    >
      {editing && (
        <p id={HELP_ID} className="sr-only">
          Widget drag handle. Press Enter to pick up this widget. Arrow keys move it, Shift and arrow keys resize it, Enter drops it and Escape
          cancels.
        </p>
      )}
      {outline && (
        <div
          aria-hidden="true"
          data-testid="drop-outline"
          className="pointer-events-none absolute rounded-widget border-2 border-dashed border-accent bg-chip transition-[left,top,width,height] duration-[240ms] ease-cc"
          style={rectOf(outline, metrics)}
        />
      )}
      {shown.items.map((item) => {
        const def = getWidget(item.widgetId);
        const source = item.sources[0] ?? def?.defaultSources[0] ?? "manual";
        const dragging = drag?.id === item.id;
        const lifted = dragging || keyed?.id === item.id;
        const rect = rectOf(item, metrics);
        const base = dragging ? itemOf(drag.base, item.id) : undefined;
        const origin = base ? rectOf(base, metrics) : rect;
        const live =
          dragging && drag.handle === "move"
            ? {
                ...origin,
                left: origin.left + drag.dx,
                top: origin.top + drag.dy,
              }
            : dragging
              ? {
                  ...origin,
                  width: Math.max(origin.width + (drag.handle === "s" ? 0 : drag.dx), metrics.colPx),
                  height: Math.max(origin.height + (drag.handle === "e" ? 0 : drag.dy), metrics.rowPx),
                }
              : rect;
        const title = titleOf(item);
        const sources = item.sources.map(sourceName).join(", ");
        const shellProps: Omit<WidgetShellProps, "state" | "children"> = {
          title,
          source,
          status: sources,
          tierBadge: tierLabel(item),
          editing,
          lifted,
          footerLeft: sources,
          // Pointer drag works from anywhere on the header; the header is not a button, so the heading stays a heading.
          headerProps: editing
            ? {
                onPointerDown: (e) => {
                  startPointer(e, item, "move");
                },
                onPointerMove: movePointer,
                onPointerUp: (e) => {
                  endPointer(e, true);
                },
                onPointerCancel: (e) => {
                  endPointer(e, false);
                },
              }
            : undefined,
          // The handle's name is built from its own content ("Move Events, W2 · H3 · 5×10"); there is no aria-label,
          // so it always contains its visible text (WCAG 2.5.3). Pick-up instructions and the pinned note come from
          // aria-describedby.
          handleProps: editing
            ? {
                "aria-describedby": item.pinned ? `${HELP_ID} pinned-${item.id}` : HELP_ID,
                "aria-pressed": keyed?.id === item.id,
                onKeyDown: (e) => {
                  onHeaderKey(e, item);
                },
                onBlur: () => {
                  onHeaderBlur(item);
                },
              }
            : undefined,
        };
        return (
          <div
            key={item.id}
            data-testid={`widget-${item.id}`}
            data-x={item.x}
            data-y={item.y}
            data-w={item.w}
            data-h={item.h}
            className={cn(
              "absolute transition-[left,top,width,height] duration-[240ms] ease-cc",
              dragging && "z-20 !transition-none",
              keyed?.id === item.id && "z-20",
            )}
            style={live}
          >
            {item.widgetId === "tasks" && def ? (
              <TasksWidget {...shellProps} widthTier={tier(item.w, item.h, def).w} heightTier={tier(item.w, item.h, def).h} />
            ) : (
              <WidgetShell {...shellProps} state={stateFor?.(item) ?? { kind: "ready" }}>
                <p className="tnum text-muted">{tierLabel(item)}</p>
              </WidgetShell>
            )}
            {editing && item.pinned && (
              <span id={`pinned-${item.id}`} className="sr-only">
                Pinned: it cannot be moved or resized.
              </span>
            )}
            {editing &&
              !item.pinned &&
              HANDLES.map(({ handle, className, cursor }) => (
                <div
                  key={handle}
                  aria-hidden="true"
                  data-testid={`handle-${handle}`}
                  className={cn("absolute z-10 touch-none", className, cursor)}
                  onPointerDown={(e) => {
                    startPointer(e, item, handle);
                  }}
                  onPointerMove={movePointer}
                  onPointerUp={(e) => {
                    endPointer(e, true);
                  }}
                  onPointerCancel={(e) => {
                    endPointer(e, false);
                  }}
                />
              ))}
          </div>
        );
      })}
    </div>
  );
}
