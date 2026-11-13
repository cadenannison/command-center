import type { Tier } from "../../layout";
import { formatClock } from "./tasks-model";
import { useEvents } from "./use-events";
import { useNow } from "./use-now";
import { WidgetShell, type WidgetShellProps, type WidgetState } from "./widget-shell";
import { deriveQueryState } from "./widget-state";
import { degrees, summaryLine, forecastDays, isOutdated, newestFetch, outlookDays, weatherWindow, type ForecastDay } from "./weather-model";

/** Fixed text: the server's error text is never shown. */
const ERROR_HINT = "Could not load the forecast. Try again.";

export interface WeatherViewProps {
  readonly days: readonly ForecastDay[];
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The forecast body, from plain days. Width tier 1: today's high and low. Tier 2 adds the rain chance and tomorrow.
 *  Tier 3 adds the multi-day outlook; height tier sets how many days (decision 0376). */
export function WeatherView({ days, widthTier, heightTier }: WeatherViewProps) {
  const today = days[0];
  if (!today) return null;
  const outlook = outlookDays(days, widthTier, heightTier);
  return (
    <div className="flex flex-col gap-2 pb-1">
      <p aria-hidden="true" className="tnum font-display text-[2.4rem] font-medium leading-none" data-testid="weather-high">
        {degrees(today.high)}
      </p>
      <p className="tnum text-muted">{summaryLine(today, widthTier)}</p>
      {outlook.length > 0 && (
        <ul className="flex flex-col" aria-label="Outlook">
          {outlook.map((day) => (
            <li key={day.key} data-testid="weather-day" className="flex min-h-7 items-center gap-2 border-b border-line last:border-b-0">
              <span className="min-w-0 flex-1 truncate">{day.label}</span>
              {widthTier >= 3 && day.rain !== null && (
                <span className="tnum flex-none text-caption text-muted">{`${String(day.rain)}% rain`}</span>
              )}
              <span className="tnum flex-none font-medium">
                {degrees(day.high)}
                <span className="text-muted">{` / ${degrees(day.low)}`}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export interface WeatherWidgetProps extends Omit<WidgetShellProps, "state" | "children" | "footerRight"> {
  readonly widthTier: Tier;
  readonly heightTier: Tier;
}

/** The Weather widget: the daily `weather` events of GET /v1/events, in the units the API sends (degrees Fahrenheit). */
export function WeatherWidget({ widthTier, heightTier, ...shell }: WeatherWidgetProps) {
  const now = useNow();
  const window = weatherWindow(now);
  const query = useEvents(window.from, window.to, "weather");
  const days = forecastDays(query.data ?? [], now);
  const derived = deriveQueryState({
    hasData: query.data !== undefined,
    isPending: query.isPending,
    isError: query.isError,
    dataUpdatedAt: query.dataUpdatedAt,
    isEmpty: days.length === 0,
  });
  const retry = () => {
    void query.refetch();
  };
  const outdated = derived.kind === "ready" && isOutdated(days, now);
  const newest = newestFetch(days);
  const state: WidgetState =
    derived.kind === "error"
      ? { kind: "error", source: "the forecast", hint: ERROR_HINT, onRetry: retry }
      : derived.kind === "stale"
        ? { kind: "stale", lastSynced: derived.lastSynced, onRetry: retry }
        : derived.kind === "empty"
          ? { kind: "not_connected", source: "Weather" }
          : outdated && newest !== null
            ? { kind: "stale", lastSynced: formatClock(new Date(newest)), onRetry: retry }
            : derived;
  return (
    <WidgetShell {...shell} state={state} footerRight="">
      <WeatherView days={days} widthTier={widthTier} heightTier={heightTier} />
    </WidgetShell>
  );
}
