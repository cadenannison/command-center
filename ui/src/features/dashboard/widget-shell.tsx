import type { ComponentProps, ReactNode } from "react";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { SourceDot, sourceName } from "../../components/ui/source-dot";
import { Skeleton } from "../../components/ui/skeleton";
import type { SourceId } from "../../lib/sources";
import { cn } from "../../lib/utils";

/** What a widget body can be showing (spec, Widget anatomy: States). One failing source never blanks the dashboard. */
export type WidgetState =
  | { readonly kind: "ready" }
  | { readonly kind: "loading" }
  | { readonly kind: "empty"; readonly message?: string }
  | {
      readonly kind: "error";
      readonly source: string;
      readonly hint?: string;
      readonly onRetry?: () => void;
    }
  | {
      readonly kind: "stale";
      readonly lastSynced: string;
      readonly onRetry?: () => void;
    }
  | {
      readonly kind: "not_connected";
      readonly source: string;
      readonly onConnect?: () => void;
    };

export interface WidgetShellProps {
  readonly title: string;
  readonly source: SourceId;
  /** The quiet status on the right of the header: last synced or the source list. */
  readonly status: string;
  /** In edit mode the status becomes this tier badge, e.g. "W2 · H3 · 5×10". */
  readonly tierBadge?: string;
  readonly state?: WidgetState;
  readonly footerLeft?: string;
  readonly footerRight?: string;
  readonly editing?: boolean;
  readonly lifted?: boolean;
  /** Pointer handlers for dragging by the header. The header itself is never a button: it holds the heading. */
  readonly headerProps?: ComponentProps<"div"> | undefined;
  /** In edit mode: the drag handle, its own button beside the heading (decision 0374). */
  readonly handleProps?: ComponentProps<"button"> | undefined;
  readonly children?: ReactNode;
  readonly className?: string;
}

function Body({ state, children }: { state: WidgetState; children: ReactNode }) {
  switch (state.kind) {
    case "loading":
      return (
        <div role="status" aria-label="Loading" className="flex flex-col gap-3">
          <Skeleton />
          <Skeleton className="w-4/5" />
          <Skeleton className="w-3/5" />
        </div>
      );
    case "empty":
      return <p className="text-muted">{state.message ?? "All clear. Nothing due."}</p>;
    case "error":
      return (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p className="text-danger">{`Can't reach ${state.source}.`}</p>
          <p className="text-muted">{state.hint ?? "Check that it is connected and try again."}</p>
          {state.onRetry && (
            <Button size="sm" variant="outline" onClick={state.onRetry}>
              Retry
            </Button>
          )}
        </div>
      );
    case "not_connected":
      return (
        <div className="flex flex-col items-start gap-2">
          <p>{`${state.source} isn't connected yet.`}</p>
          {state.onConnect && (
            <Button size="sm" variant="outline" onClick={state.onConnect}>
              Connect
            </Button>
          )}
        </div>
      );
    case "stale":
      return (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-muted">
            <span>{`Showing older data. Last synced ${state.lastSynced}.`}</span>
            {state.onRetry && (
              <Button size="sm" variant="outline" onClick={state.onRetry}>
                Retry
              </Button>
            )}
          </div>
          {children}
        </div>
      );
    case "ready":
      return <>{children}</>;
  }
}

/** The glass shell every widget shares: header, scrolling body, footer. The body is whatever the widget passes. */
export function WidgetShell({
  title,
  source,
  status,
  tierBadge,
  state = { kind: "ready" },
  footerLeft,
  footerRight,
  editing = false,
  lifted = false,
  headerProps,
  handleProps,
  children,
  className,
}: WidgetShellProps) {
  const { className: headerClass, ...header } = headerProps ?? {};
  return (
    <Card
      source={source}
      data-state={state.kind}
      className={cn("flex h-full min-h-0 flex-col overflow-hidden", lifted && "ring-2 ring-accent", className)}
    >
      <div
        {...header}
        className={cn(
          "flex h-11 flex-none items-center gap-2 px-4",
          editing && "cursor-grab touch-none select-none",
          headerClass,
        )}
      >
        <SourceDot source={source} />
        <h2 className="min-w-0 flex-1 truncate font-display text-base font-semibold">{title}</h2>
        {editing && handleProps ? (
          <button
            type="button"
            tabIndex={0}
            {...handleProps}
            className="tnum inline-flex min-h-7 flex-none cursor-grab touch-none select-none items-center gap-1 rounded-control px-2 text-caption text-muted focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <svg viewBox="0 0 8 12" width="8" height="12" fill="currentColor" aria-hidden="true">
              <circle cx="2" cy="2" r="1" />
              <circle cx="6" cy="2" r="1" />
              <circle cx="2" cy="6" r="1" />
              <circle cx="6" cy="6" r="1" />
              <circle cx="2" cy="10" r="1" />
              <circle cx="6" cy="10" r="1" />
            </svg>
            {/* The name is built from content, so it always contains the visible badge text (WCAG 2.5.3). */}
            <span className="sr-only">{`Move ${title},`}</span>{" "}
            <span>{tierBadge ?? ""}</span>
          </button>
        ) : (
          <span className="tnum flex-none text-caption text-muted">{editing && tierBadge ? tierBadge : status}</span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-2">
        <Body state={state}>{children}</Body>
      </div>
      <div className="flex h-8 flex-none items-center justify-between px-4 text-caption text-muted">
        <span>{footerLeft ?? sourceName(source)}</span>
        <span className="tnum">{footerRight ?? ""}</span>
      </div>
    </Card>
  );
}
