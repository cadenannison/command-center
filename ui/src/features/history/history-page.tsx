import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { summaryDay } from "../dashboard/summary-model";
import { formatClock } from "../dashboard/tasks-model";
import { useNow } from "../dashboard/use-now";
import { useItemActions } from "../items/use-item-actions";
import { buildDays, historyRange, OUTCOME_LABEL, type HistoryFilter, type HistoryRow } from "./history-model";
import { useHistory } from "./use-history";

/** Fixed texts: the server's error text is never shown. */
const ERROR_TEXT = "Could not load history. Try again.";
const STALE_TEXT = "Couldn't refresh. Showing your last loaded history.";

const FILTERS: readonly { readonly value: HistoryFilter; readonly label: string }[] = [
  { value: "all", label: "All" },
  { value: "done", label: "Done" },
  { value: "dismissed", label: "Dismissed" },
];

interface EntryProps {
  readonly row: HistoryRow;
  readonly onRestore: () => void;
  readonly busy: boolean;
  /** Registers the Restore button under the row's key, so focus can move to it. */
  readonly buttonRef: (key: string, el: HTMLButtonElement | null) => void;
}

function Entry({ row, onRestore, busy, buttonRef }: EntryProps) {
  const { entry } = row;
  return (
    <li data-testid="history-entry" data-outcome={entry.outcome} className="flex items-center gap-3 border-b border-line py-2 last:border-b-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <span data-sensitive className="truncate font-medium">
          {entry.title}
        </span>
        {entry.note && (
          <span data-sensitive className="truncate text-caption text-muted">
            {entry.note}
          </span>
        )}
      </div>
      <span className="flex-none text-caption text-muted">{OUTCOME_LABEL[entry.outcome]}</span>
      <span className="tnum flex-none text-caption text-muted">{formatClock(new Date(entry.at))}</span>
      {row.restorable && (
        // The name starts with the visible word (label in name); the title tells the Restore buttons apart.
        <Button
          ref={(el) => {
            buttonRef(row.key, el);
          }}
          size="sm"
          variant="outline"
          disabled={busy}
          aria-label={`Restore ${entry.title}`}
          onClick={onRestore}
        >
          Restore
        </Button>
      )}
    </li>
  );
}

/** The History page (decision 0403): done and dismissed items by day, newest first, with search, filters and Restore. */
export function HistoryPage() {
  const now = useNow();
  const { from, to } = historyRange(now);
  const query = useHistory(from, to);
  const actions = useItemActions();
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [search, setSearch] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  // After a Restore: the key of the entry that should leave and the key of the next restorable entry (or null).
  const pendingFocus = useRef<{ removed: string; next: string | null } | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const retry = () => {
    void query.refetch();
  };

  const days = query.data === undefined ? [] : buildDays(query.data, filter, search, summaryDay(now));
  const hasAny = (query.data ?? []).length > 0;

  // The restored entry leaves the list and takes focus with it: once the refetch has settled, focus the next entry's
  // Restore button, or the page heading when there is none (decision 0403).
  const rowKeys = days.flatMap((d) => d.rows.map((r) => r.key)).join("|");
  useEffect(() => {
    const pending = pendingFocus.current;
    if (!pending || query.isFetching) return;
    pendingFocus.current = null;
    if (!rowKeys.split("|").includes(pending.removed)) {
      const next = pending.next === null ? undefined : buttons.current.get(pending.next);
      (next ?? heading.current)?.focus();
    }
  }, [focusTick, query.isFetching, rowKeys]);

  const restoreRow = (row: HistoryRow) => {
    const flat = days.flatMap((d) => d.rows);
    const after = flat.slice(flat.indexOf(row) + 1).find((r) => r.restorable);
    actions.restore({ id: row.entry.item_id, title: row.entry.title }, () => {
      pendingFocus.current = { removed: row.key, next: after?.key ?? null };
      setFocusTick((n) => n + 1);
    });
  };

  let body;
  if (query.data === undefined) {
    body = query.isError ? (
      <div role="alert" className="flex flex-col items-start gap-2">
        <p className="text-danger">{ERROR_TEXT}</p>
        <Button size="sm" variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    ) : (
      <div role="status" aria-label="Loading" className="flex flex-col gap-3">
        <Skeleton />
        <Skeleton className="w-4/5" />
        <Skeleton className="w-3/5" />
      </div>
    );
  } else if (!hasAny) {
    body = <p className="text-muted">Nothing done or dismissed in the last 30 days.</p>;
  } else if (days.length === 0) {
    body = <p className="text-muted">Nothing matches.</p>;
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {days.map((day) => (
          <section key={day.day} aria-labelledby={`history-${day.day}`} data-testid="history-day">
            <div className="flex items-baseline gap-3 border-b border-line pb-1">
              <h2 id={`history-${day.day}`} className="m-0 font-display text-base font-semibold">
                {day.heading}
              </h2>
              <span className="tnum text-caption text-muted">{`${String(day.done)} done, ${String(day.dismissed)} dismissed`}</span>
            </div>
            <ul>
              {day.rows.map((row) => (
                <Entry
                  key={row.key}
                  row={row}
                  busy={actions.busy}
                  buttonRef={(key, el) => {
                    if (el) buttons.current.set(key, el);
                    else buttons.current.delete(key);
                  }}
                  onRestore={() => {
                    restoreRow(row);
                  }}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="m-0 font-display text-xl font-semibold">
        History
      </h1>
      <p className="m-0 text-muted">Done and dismissed items from the last 30 days. You can restore today's.</p>
      {query.data !== undefined && query.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-muted">
          <span>{STALE_TEXT}</span>
          <Button size="sm" variant="outline" disabled={query.isFetching} onClick={retry}>
            Retry
          </Button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2">
          <span>Search</span>
          <input
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
            className="min-h-8 rounded-control border border-line2 bg-chip px-3"
          />
        </label>
        <fieldset className="m-0 flex items-center gap-3 border-0 p-0">
          <legend className="sr-only">Show</legend>
          {FILTERS.map(({ value, label }) => (
            <label key={value} className="flex min-h-8 items-center gap-1">
              <input
                type="radio"
                name="history-filter"
                value={value}
                checked={filter === value}
                onChange={() => {
                  setFilter(value);
                }}
              />
              {label}
            </label>
          ))}
        </fieldset>
      </div>
      {body}
    </div>
  );
}
