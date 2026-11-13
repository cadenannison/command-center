import { SourceDot, sourceName } from "../../components/ui/source-dot";
import type { Tier } from "../../layout";
import { cn } from "../../lib/utils";
import {
  buildAgenda,
  eventRowsOf,
  eventsWindow,
  limitAgenda,
  showsDetail,
  showsMarkers,
  showsPast,
  timeText,
  untilText,
  type Agenda,
  type AgendaRow,
} from "./events-model";
import { useEvents } from "./use-events";
import { useNow } from "./use-now";
import { WidgetShell, type WidgetShellProps, type WidgetState } from "./widget-shell";
import { deriveQueryState } from "./widget-state";

/** Fixed text: the server's error text is never shown. */
const ERROR_HINT = "Could not load your events. Try again.";

function LinkIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 013.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 014.5 9l1-1" strokeLinecap="round" />
    </svg>
  );
}

function EventRowView({ row, widthTier }: { row: AgendaRow; widthTier: Tier }) {
  const { event } = row;
  const detail = showsDetail(widthTier);
  const marker = showsMarkers(widthTier) ? row.marker : null;
  const meta = [detail ? untilText(row) : "", detail ? (event.location ?? "") : ""].filter((part) => part !== "");
  return (
    <li
      data-testid="event-row"
      data-marker={marker ?? undefined}
      className="flex min-h-8 items-center gap-2 border-b border-line py-1 last:border-b-0"
    >
      <span className="tnum w-[4.5rem] flex-none font-display text-caption text-muted">{timeText(row)}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span data-sensitive className={cn("truncate", marker === "next" ? "font-semibold" : "font-medium")}>
          {event.title}
        </span>
        {meta.length > 0 && (
          <span className="tnum truncate text-caption text-muted">
            {detail && untilText(row) !== "" && <span>{untilText(row)}</span>}
            {detail && untilText(row) !== "" && event.location && " · "}
            {detail && event.location && <span data-sensitive>{event.location}</span>}
          </span>
        )}
      </span>
      {marker === "now" && <span className="flex-none rounded-control bg-chip px-1.5 text-caption font-semibold">Now</span>}
      {marker === "next" && <span className="flex-none rounded-control bg-chip px-1.5 text-caption font-semibold">Next</span>}
      {detail && <SourceDot source={event.source} label={sourceName(event.source)} />}
      {event.href && (
        <a
          href={event.href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${event.title} in a new tab`}
          className="inline-flex size-8 flex-none items-center justify-center rounded-control text-muted hover:text-fg"
        >
          <LinkIcon />
        </a>
      )}
    </li>
  );
}

export interface EventsViewProps {
  readonly agenda: Agenda;
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The agenda body, from plain data: day groups, rows limited by height tier and "+N more" (decision 0378). */
export function EventsView({ agenda, widthTier, heightTier }: EventsViewProps) {
  const { days, more } = limitAgenda(agenda, heightTier);
  return (
    <div className="flex flex-col gap-2">
      {days.map((day) => (
        <section key={day.key} aria-label={day.label} className="flex flex-col">
          <h3 className="text-caption font-semibold uppercase tracking-wide text-muted">{day.label}</h3>
          <ul>
            {day.rows.map((row) => (
              <EventRowView key={`${day.key}-${row.event.id}`} row={row} widthTier={widthTier} />
            ))}
          </ul>
        </section>
      ))}
      {more > 0 && (
        <p data-testid="events-more" className="tnum text-caption text-muted">
          {`+${String(more)} more`}
        </p>
      )}
    </div>
  );
}

export interface EventsWidgetProps extends Omit<WidgetShellProps, "state" | "children" | "footerRight"> {
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The Events widget: calendar events of GET /v1/events for today and the next six local days (decision 0378). */
export function EventsWidget({ widthTier, heightTier, ...shell }: EventsWidgetProps) {
  const now = useNow();
  const span = eventsWindow(now);
  const query = useEvents(span.from, span.to, "events");
  const agenda = buildAgenda(eventRowsOf(query.data ?? []), now, showsPast(heightTier));
  const derived = deriveQueryState({
    hasData: query.data !== undefined,
    isPending: query.isPending,
    isError: query.isError,
    dataUpdatedAt: query.dataUpdatedAt,
    isEmpty: agenda.total === 0,
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
          ? { kind: "empty", message: "Nothing on your calendar." }
          : derived;
  const showBody = state.kind === "ready" || state.kind === "stale";
  const today = agenda.days.find((day) => day.offset === 0)?.rows.length ?? 0;
  return (
    <WidgetShell {...shell} state={state} footerRight={showBody ? `${String(today)} today` : ""}>
      <EventsView agenda={agenda} widthTier={widthTier} heightTier={heightTier} />
    </WidgetShell>
  );
}
