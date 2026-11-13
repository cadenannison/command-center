import { useId, useState } from "react";
import { Pill } from "../../components/ui/pill";
import { SourceDot, sourceName } from "../../components/ui/source-dot";
import type { Tier } from "../../layout";
import { cn } from "../../lib/utils";
import {
  countText,
  isOverdue,
  kindLabel,
  limitRows,
  needsMeRows,
  rowLimit,
  rowSource,
  whenLabel,
  type NeedsMeItem,
} from "./needs-me-model";
import { formatPoints, safeHref, topReason } from "./tasks-model";
import { useNeedsMe } from "./use-needs-me";
import { useNow } from "./use-now";
import { WidgetShell, type WidgetShellProps, type WidgetState } from "./widget-shell";
import { deriveQueryState } from "./widget-state";

/** Fixed text: the server's error text is never shown. */
const ERROR_HINT = "Could not load what needs you. Try again.";

function LinkIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 013.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 014.5 9l1-1" strokeLinecap="round" />
    </svg>
  );
}

function NeedsMeRow({ item, now, widthTier }: { item: NeedsMeItem; now: number; widthTier: Tier }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const href = safeHref(item.link);
  const reason = topReason(item.reasons);
  const when = whenLabel(item, now);
  const source = rowSource(item);
  return (
    <li data-testid="needs-me-row" data-kind={item.kind} className="border-b border-line py-1 last:border-b-0">
      <div className="flex min-h-8 items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          className="min-h-8 min-w-0 flex-1 truncate rounded-control text-left font-medium"
          onClick={() => {
            setOpen(!open);
          }}
        >
          {item.title}
        </button>
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
      <p className="flex items-center gap-2 text-caption text-muted">
        {widthTier >= 2 && <SourceDot source={source} label={sourceName(source)} />}
        <span data-testid="needs-me-kind">{kindLabel(item.kind) ?? ""}</span>
        {when !== "" && (
          <span className={cn("tnum", isOverdue(item, now) && "font-semibold text-danger")} data-testid="needs-me-when">
            {when}
          </span>
        )}
      </p>
      {widthTier >= 3 && reason && !open && <p className="pb-1 text-caption text-muted">{reason.text}</p>}
      <div id={panelId} hidden={!open}>
        {open && (
          <ul className="flex flex-col gap-1 pb-2 pl-2 text-caption text-muted">
            {item.reasons.length === 0 && <li>No reasons recorded.</li>}
            {item.reasons.map((r, i) => (
              <li key={`${r.code}-${String(i)}`} className="flex gap-2">
                <span className="flex-1">{r.text}</span>
                <span className="tnum flex-none">
                  {formatPoints(r.points)}
                  <span className="sr-only"> points</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export interface NeedsMeViewProps {
  /** Already the server's order, weather removed. */
  readonly rows: readonly NeedsMeItem[];
  readonly now: number;
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The list body from plain rows. Width tier 1 shows the count and the top item only; wider tiers show a ranked list
 *  cut by height tier with "+N more" (decision 0387). */
export function NeedsMeView({ rows, now, widthTier, heightTier }: NeedsMeViewProps) {
  const compact = widthTier === 1;
  const { shown, more } = limitRows(rows, compact ? 1 : rowLimit(heightTier));
  return (
    <div className="flex flex-col gap-1">
      {compact && (
        <p data-testid="needs-me-count" className="tnum font-display text-lg font-semibold">
          {countText(rows.length)}
        </p>
      )}
      <ul>
        {shown.map((item) => (
          <NeedsMeRow key={item.id} item={item} now={now} widthTier={widthTier} />
        ))}
      </ul>
      {more > 0 && !compact && (
        <p data-testid="needs-me-more" className="tnum text-caption text-muted">
          {`+${String(more)} more`}
        </p>
      )}
    </div>
  );
}

export interface NeedsMeWidgetProps extends Omit<WidgetShellProps, "state" | "children" | "footerRight"> {
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The Needs me widget: GET /v1/needs-me, read-only, in the server's order (decisions 0385 to 0387). */
export function NeedsMeWidget({ widthTier, heightTier, ...shell }: NeedsMeWidgetProps) {
  const query = useNeedsMe();
  const now = useNow();
  const rows = needsMeRows(query.data ?? []);
  const derived = deriveQueryState({
    hasData: query.data !== undefined,
    isPending: query.isPending,
    isError: query.isError,
    dataUpdatedAt: query.dataUpdatedAt,
    isEmpty: rows.length === 0,
  });
  const retry = () => {
    void query.refetch();
  };
  const state: WidgetState =
    derived.kind === "error"
      ? { kind: "error", source: "the Needs me list", hint: ERROR_HINT, onRetry: retry }
      : derived.kind === "stale"
        ? { kind: "stale", lastSynced: derived.lastSynced, onRetry: retry }
        : derived.kind === "empty"
          ? { kind: "empty", message: "Nothing needs you right now" }
          : derived;
  const showBody = state.kind === "ready" || state.kind === "stale";
  return (
    <WidgetShell {...shell} state={state} footerRight={showBody ? countText(rows.length) : ""}>
      <NeedsMeView rows={rows} now={now} widthTier={widthTier} heightTier={heightTier} />
    </WidgetShell>
  );
}
