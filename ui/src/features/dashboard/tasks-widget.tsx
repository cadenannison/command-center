import { useEffect, useId, useState } from "react";
import { SourceDot } from "../../components/ui/source-dot";
import { Pill } from "../../components/ui/pill";
import type { Tier } from "../../layout";
import { RowActions } from "../items/row-actions";
import { cn } from "../../lib/utils";
import { WidgetShell, type WidgetShellProps, type WidgetState } from "./widget-shell";
import {
  deriveTasksState,
  formatDue,
  formatPoints,
  groupTasks,
  limitRows,
  openCount,
  rowLimit,
  safeHref,
  sourceIdOf,
  topReason,
  type TaskGroup,
  type TaskItem,
} from "./tasks-model";
import { useTasks } from "./use-tasks";

/** Fixed text: the server's error text is never shown. */
const ERROR_HINT = "Could not load tasks. Try again.";

function LinkIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 013.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 014.5 9l1-1" strokeLinecap="round" />
    </svg>
  );
}

function TaskRow({ item, now, widthTier }: { item: TaskItem; now: number; widthTier: Tier }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const href = safeHref(item.link);
  const reason = topReason(item.reasons);
  const due = widthTier >= 2 ? formatDue(item.due, now) : "";
  return (
    <li data-testid="task-row" className="border-b border-line py-1 last:border-b-0">
      <div className="flex min-h-8 items-center gap-2">
        <button
          type="button"
          data-sensitive
          aria-expanded={open}
          aria-controls={panelId}
          className="min-h-8 min-w-0 flex-1 truncate rounded-control text-left font-medium"
          onClick={() => {
            setOpen(!open);
          }}
        >
          {item.title}
        </button>
        {widthTier >= 2 && (
          <>
            {due && <span className="tnum flex-none text-caption text-muted">{due}</span>}
            <SourceDot source={sourceIdOf(item.source)} />
          </>
        )}
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open ${item.title} in a new tab`}
            className="inline-flex size-8 flex-none items-center justify-center rounded-control text-muted hover:text-fg"
          >
            <LinkIcon />
          </a>
        )}
        <Pill priority={item.priority} />
      </div>
      {widthTier >= 3 && reason && !open && <p data-sensitive className="pb-1 text-caption text-muted">{reason.text}</p>}
      <div id={panelId} hidden={!open}>
        {open && (
          <>
            <ul className="flex flex-col gap-1 pb-2 pl-2 text-caption text-muted">
              {item.reasons.length === 0 && <li>No reasons recorded.</li>}
              {item.reasons.map((r, i) => (
                <li key={`${r.code}-${String(i)}`} className="flex gap-2">
                  <span data-sensitive className="flex-1">{r.text}</span>
                  <span className="tnum flex-none">
                    {formatPoints(r.points)}
                    <span className="sr-only"> points</span>
                  </span>
                </li>
              ))}
            </ul>
            <RowActions item={{ id: item.id, title: item.title }} />
          </>
        )}
      </div>
    </li>
  );
}

export interface TasksListProps {
  readonly groups: readonly TaskGroup[];
  readonly more: number;
  readonly now: number;
  readonly widthTier: Tier;
}

/** The grouped rows. Pure of data fetching, so it renders in a test from plain items. */
export function TasksList({ groups, more, now, widthTier }: TasksListProps) {
  return (
    <div className="flex flex-col gap-1">
      {groups.map((group) => (
        <section key={group.id} aria-label={group.label}>
          <h3
            className={cn(
              "pt-1 text-caption font-semibold uppercase tracking-wide",
              group.id === "overdue" ? "text-danger" : "text-muted",
            )}
          >
            {group.label}
          </h3>
          <ul>
            {group.items.map((item) => (
              <TaskRow key={item.id} item={item} now={now} widthTier={widthTier} />
            ))}
          </ul>
        </section>
      ))}
      {more > 0 && <p className="tnum text-caption text-muted">{`+${String(more)} more`}</p>}
    </div>
  );
}

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 60_000);
    return () => {
      clearInterval(timer);
    };
  }, []);
  return now;
}

export interface TasksWidgetProps extends Omit<WidgetShellProps, "state" | "children" | "footerRight"> {
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The Tasks widget body: GET /v1/tasks, read-only. Passes its loading, empty, error and stale state to the shell. */
export function TasksWidget({ widthTier, heightTier, ...shell }: TasksWidgetProps) {
  const query = useTasks();
  const now = useNow();
  const derived = deriveTasksState({
    data: query.data,
    isPending: query.isPending,
    isError: query.isError,
    dataUpdatedAt: query.dataUpdatedAt,
  });
  const retry = () => {
    void query.refetch();
  };
  const state: WidgetState =
    derived.kind === "error"
      ? { kind: "error", source: "tasks", hint: ERROR_HINT, onRetry: retry }
      : derived.kind === "stale"
        ? { kind: "stale", lastSynced: derived.lastSynced, onRetry: retry }
        : derived;

  const all = groupTasks(query.data ?? [], now);
  const { groups, more } = limitRows(all, rowLimit(heightTier));
  const open = openCount(all);
  return (
    <WidgetShell
      {...shell}
      state={state}
      footerRight={state.kind === "ready" || state.kind === "stale" ? `${String(open)} open` : ""}
    >
      <TasksList groups={groups} more={more} now={now} widthTier={widthTier} />
    </WidgetShell>
  );
}
