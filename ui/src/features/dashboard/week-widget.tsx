import { SourceDot } from "../../components/ui/source-dot";
import type { SourceId } from "../../lib/sources";
import type { Tier } from "../../layout";
import { cn } from "../../lib/utils";
import { formatClock, formatDue } from "./tasks-model";
import { useEvents } from "./use-events";
import { useNow } from "./use-now";
import { WidgetShell, type WidgetShellProps, type WidgetState } from "./widget-shell";
import { deriveQueryState } from "./widget-state";
import {
  buildWeek,
  countText,
  dayLabel,
  itemsPerDay,
  localFirstDay,
  showsNext,
  weekItemsOf,
  weekWindow,
  type Week,
} from "./week-model";

/** Fixed text: the server's error text is never shown. */
const ERROR_HINT = "Could not load your week. Try again.";

export interface WeekStripProps {
  readonly week: Week;
  readonly now: number;
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The seven-day strip, the next event and (when tall) each day's first events. Pure of fetching, so it renders from plain data. */
export function WeekStrip({ week, now, widthTier, heightTier }: WeekStripProps) {
  const perDay = itemsPerDay(heightTier);
  return (
    <div className="flex flex-col gap-2">
      <ol className="grid grid-cols-7 gap-1" aria-label="Days of this week">
        {week.days.map((day) => (
          <li
            key={day.key}
            data-testid="week-day"
            data-today={day.isToday ? "true" : "false"}
            aria-current={day.isToday ? "date" : undefined}
            aria-label={`${dayLabel(day)}${day.isToday ? ", today" : ""}: ${countText(day.items.length)}`}
            className={cn(
              "flex min-w-0 flex-col items-center gap-1 rounded-control px-1 py-1",
              day.isToday ? "bg-chip ring-2 ring-accent" : "border border-line",
            )}
          >
            <span aria-hidden="true" className="text-caption text-muted">
              {day.weekday}
            </span>
            <span aria-hidden="true" className="tnum font-display font-semibold">
              {day.dayOfMonth}
            </span>
            <span aria-hidden="true" className="tnum text-caption text-muted">
              {day.items.length}
            </span>
            {widthTier >= 2 && (
              <span aria-hidden="true" className="flex min-h-2 gap-0.5">
                {day.sources.map((source: SourceId) => (
                  <SourceDot key={source} source={source} />
                ))}
              </span>
            )}
          </li>
        ))}
      </ol>
      {showsNext(heightTier) && (
        <p className="text-muted" data-testid="week-next">
          {week.next
            ? week.next.ongoing
              ? `Now: ${week.next.item.title}`
              : `Next: ${week.next.item.title}, ${formatDue(new Date(week.next.item.startMs).toISOString(), now)}`
            : "Nothing more this week."}
        </p>
      )}
      {perDay > 0 && (
        <ul className="flex flex-col gap-1">
          {week.days
            .filter((day) => day.items.length > 0)
            .map((day) => (
              <li key={day.key} className="flex flex-col">
                <h3 className={cn("text-caption font-semibold uppercase tracking-wide", day.isToday ? "text-fg" : "text-muted")}>
                  {`${day.weekday} ${String(day.dayOfMonth)}`}
                </h3>
                <ul>
                  {day.items.slice(0, perDay).map((item) => (
                    <li key={item.id} data-testid="week-item" className="flex min-h-6 items-center gap-2">
                      <span className="tnum flex-none text-caption text-muted">{formatClock(new Date(item.startMs))}</span>
                      <span className="min-w-0 flex-1 truncate">{item.title}</span>
                      <SourceDot source={item.source} />
                    </li>
                  ))}
                  {day.items.length > perDay && (
                    <li className="tnum text-caption text-muted">{`+${String(day.items.length - perDay)} more`}</li>
                  )}
                </ul>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

export interface WeekWidgetProps extends Omit<WidgetShellProps, "state" | "children" | "footerRight"> {
  readonly widthTier: Tier;
  readonly heightTier: Tier;
  readonly sources: readonly SourceId[];
}

/** The This week widget: GET /v1/events for the local week, grouped by local day in pure helpers (decision 0377). */
export function WeekWidget({ widthTier, heightTier, sources, ...shell }: WeekWidgetProps) {
  const now = useNow();
  const firstDay = localFirstDay();
  const window = weekWindow(now, firstDay);
  const query = useEvents(window.from, window.to, "week");
  const week = buildWeek(weekItemsOf(query.data ?? [], sources), now, firstDay);
  const derived = deriveQueryState({
    hasData: query.data !== undefined,
    isPending: query.isPending,
    isError: query.isError,
    dataUpdatedAt: query.dataUpdatedAt,
    isEmpty: week.total === 0,
  });
  const retry = () => {
    void query.refetch();
  };
  const state: WidgetState =
    derived.kind === "error"
      ? { kind: "error", source: "your calendar", hint: ERROR_HINT, onRetry: retry }
      : derived.kind === "stale"
        ? { kind: "stale", lastSynced: derived.lastSynced, onRetry: retry }
        : derived.kind === "empty"
          ? { kind: "empty", message: "Nothing scheduled this week." }
          : derived;
  const showBody = state.kind === "ready" || state.kind === "stale";
  return (
    <WidgetShell
      {...shell}
      state={state}
      footerRight={showBody ? `${String(week.total)} this week` : ""}
    >
      <WeekStrip week={week} now={now} widthTier={widthTier} heightTier={heightTier} />
    </WidgetShell>
  );
}

