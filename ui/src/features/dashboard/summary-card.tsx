import { useId, useState } from "react";
import { ApiError } from "../../api/errors";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { cn } from "../../lib/utils";
import { producedBy, privacyLines } from "./summary-privacy";
import {
  deriveSummaryState,
  fallbackNotice,
  limitPriorities,
  parseSummary,
  summaryDay,
  tierFor,
  type Cols,
  type SummaryModel,
} from "./summary-model";
import { useNow } from "./use-now";
import { useSummary } from "./use-summary";

/** Fixed text: the server's error text is never shown. */
const ERROR_TEXT = "Could not load the summary. Try again.";
const REFRESH_TEXT = "Couldn't refresh the summary. Showing the last one.";
const OFF_TEXT = "They can be turned on in Settings.";

function Entries({ title, items }: { title: string; items: readonly string[] }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h3 className="text-caption font-semibold uppercase tracking-wide text-muted">{title}</h3>
      <ul className="flex flex-col gap-1">
        {items.map((text, index) => (
          // Plain text nodes only: React escapes them, and nothing here parses HTML or links.
          <li key={`${String(index)}-${text}`} data-sensitive className="break-words">
            {text}
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface SummaryContentProps {
  readonly model: SummaryModel;
  readonly cols: Cols;
  readonly expanded: boolean;
}

/** The summary from plain data. Collapsed: the headline only. Expanded: priorities by column tier, "+N more" when cut,
 *  the heads-up below (8 columns) or beside (12), and who wrote it (decision 0381). */
export function SummaryContent({ model, cols, expanded }: SummaryContentProps) {
  const tier = tierFor(cols);
  const { shown, more } = limitPriorities(model.priorities, cols);
  const notice = fallbackNotice(model.kind);
  const headsUp = tier.headsUp !== "none" && model.headsUp.length > 0 ? model.headsUp : [];
  return (
    <div className="flex flex-col gap-2">
      <p data-sensitive data-testid="summary-headline" className="break-words font-display text-base font-medium">
        {model.headline}
      </p>
      {notice && (
        <p data-testid="summary-notice" className="text-caption text-muted">
          {notice}
        </p>
      )}
      {expanded && (
        <>
          <div data-testid="summary-details" className={cn("grid gap-4", tier.headsUp === "beside" ? "grid-cols-2" : "grid-cols-1")}>
            {(shown.length > 0 || more > 0) && (
              <div className="flex min-w-0 flex-col gap-1">
                <Entries title="Priorities" items={shown} />
                {more > 0 && (
                  <p data-testid="summary-more" className="tnum text-caption text-muted">
                    {`+${String(more)} more`}
                  </p>
                )}
              </div>
            )}
            {headsUp.length > 0 && <Entries title="Heads up" items={headsUp} />}
          </div>
          {model.kind === "fresh" && (
            <div data-testid="summary-caption" className="flex flex-col text-caption text-muted">
              <p>{producedBy(model.provider)}</p>
              {privacyLines().map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export interface SummaryCardProps {
  /** 4, 8 or 12 (the same count the grid uses). */
  readonly cols: Cols;
}

/** The Summary card, pinned above the grid and collapsible (docs/design/spec.md; not a grid widget, decision 0381).
 *  It reads GET /v1/summary for the local day once per mount. */
export function SummaryCard({ cols }: SummaryCardProps) {
  const headingId = useId();
  const now = useNow();
  const query = useSummary(summaryDay(now));
  const [expanded, setExpanded] = useState(true);
  const state = deriveSummaryState({
    isPending: query.isPending,
    isError: query.isError,
    errorKind: query.error instanceof ApiError ? query.error.kind : null,
    model: query.data === undefined ? null : parseSummary(query.data),
    hasData: query.data !== undefined,
  });
  const retry = () => {
    void query.refetch();
  };
  return (
    <section
      aria-labelledby={headingId}
      data-testid="summary-card"
      data-state={state.kind}
      className="glass glow flex flex-col gap-2 px-4 py-3"
    >
      <div className="flex items-center gap-2">
        <h2 id={headingId} className="min-w-0 flex-1 font-display text-base font-semibold">
          Summary
        </h2>
        {state.kind === "ready" && (
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => {
              setExpanded(!expanded);
            }}
            className="inline-flex min-h-8 flex-none items-center rounded-control px-2 text-caption text-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {expanded ? "Collapse " : "Expand "}
            <span className="sr-only">summary</span>
          </button>
        )}
      </div>
      {state.kind === "loading" && (
        <div role="status" aria-label="Loading" className="flex flex-col gap-2">
          <Skeleton />
          <Skeleton className="w-3/5" />
        </div>
      )}
      {state.kind === "off" && (
        <div className="flex flex-col gap-1">
          <p className="font-medium">Summaries are off</p>
          <p className="text-muted">{OFF_TEXT}</p>
        </div>
      )}
      {state.kind === "error" && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          <p className="text-danger">{ERROR_TEXT}</p>
          <Button size="sm" variant="outline" onClick={retry}>
            Retry
          </Button>
        </div>
      )}
      {state.kind === "ready" && (
        <>
          {state.refreshFailed && (
            <div role="status" className="flex flex-wrap items-center gap-2 text-muted">
              <span>{REFRESH_TEXT}</span>
              <Button size="sm" variant="outline" onClick={retry}>
                Retry
              </Button>
            </div>
          )}
          <SummaryContent model={state.model} cols={cols} expanded={expanded} />
        </>
      )}
    </section>
  );
}
