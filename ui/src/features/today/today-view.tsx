import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import type { AgendaItem, StaleInfo, TodayState } from "./state";

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function StaleNotice({ stale, onRetry }: { stale: StaleInfo; onRetry: () => void }) {
  return (
    <p role="status">
      {stale.refreshFailed ? "Could not refresh. " : ""}Showing data from {formatTime(new Date(stale.since).toISOString())}.{" "}
      <Button size="sm" variant="outline" onClick={onRetry}>
        Refresh
      </Button>
    </p>
  );
}

function Rows({ items }: { items: readonly AgendaItem[] }) {
  return (
    <ul>
      {items.map((item) => (
        <li key={item.id}>
          {formatTime(item.start)} <span data-sensitive>{item.title}</span> ({item.kind}, {item.source})
        </li>
      ))}
    </ul>
  );
}

/** Unstyled rows for the four states. No visual design yet (task P1b); the markup is plain and accessible. */
export function TodayView({ state, onRetry }: { state: TodayState; onRetry: () => void }) {
  switch (state.kind) {
    case "loading":
      return (
        <div role="status" aria-busy="true" aria-label="Loading today">
          <Skeleton className="mb-2 w-2/3" />
          <Skeleton className="mb-2 w-1/2" />
          <Skeleton className="w-3/5" />
        </div>
      );
    case "error":
      return (
        <div role="alert">
          <p>{state.message}</p>
          <Button variant="outline" onClick={onRetry}>
            Try again
          </Button>
        </div>
      );
    case "empty":
      return (
        <div>
          {state.stale ? <StaleNotice stale={state.stale} onRetry={onRetry} /> : null}
          <p>Nothing scheduled today.</p>
        </div>
      );
    case "ready":
      return (
        <div>
          {state.stale ? <StaleNotice stale={state.stale} onRetry={onRetry} /> : null}
          <Rows items={state.items} />
        </div>
      );
  }
}
