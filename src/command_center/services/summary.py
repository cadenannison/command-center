"""The opt-in daily summary: cache, provider, fallbacks. Decisions: 0034, 0035."""

import asyncio
import logging
from datetime import date, tzinfo

from pydantic import BaseModel, ConfigDict

from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.ports import Clock, SummaryProvider, SummaryStore
from command_center.core.schema import Event
from command_center.core.summary import DailySummary, build_prompt, template_summary
from command_center.services.agenda import AgendaService
from command_center.services.errors import SummaryUnavailableError

logger = logging.getLogger(__name__)

PROVIDER_TEMPLATE = "template"
PROVIDER_STORED = "stored"


class SummaryResult(BaseModel):
    """A summary and where it came from.

    `provider` is the provider's name for a fresh or cached summary, `"stored"` when an earlier
    day's summary stands in after a provider failure, and `"template"` for the built-in fallback.
    `cached` is true when the summary came from the store rather than from a provider call.
    """

    model_config = ConfigDict(frozen=True)

    summary: DailySummary
    provider: str
    cached: bool


def summary_text(summary: DailySummary) -> str:
    """The summary as plain text: the headline, then its priorities and heads-up lines."""
    lines = [summary.headline]
    if summary.priorities:
        lines.append("Priorities: " + "; ".join(summary.priorities))
    if summary.heads_up:
        lines.append("Heads up: " + "; ".join(summary.heads_up))
    return "\n".join(lines)


class SummaryService:
    """Builds the day's summary at most once per day, and never fails because a provider did.

    The composition root builds this only when the user has opted in (`summary_enabled`); with no
    service there is no provider, so nothing is ever sent anywhere (decision 0004).
    """

    def __init__(  # noqa: PLR0913
        self,
        agenda: AgendaService,
        store: SummaryStore,
        provider: SummaryProvider,
        clock: Clock,
        tz: tzinfo,
        *,
        include_email: bool = False,
    ) -> None:
        self._agenda = agenda
        self._store = store
        self._provider = provider
        self._clock = clock
        self._tz = tz
        self._include_email = include_email
        # One user, one provider: serialising keeps two requests from paying for the same day twice.
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        """The name of the provider this service calls."""
        return self._provider.name

    async def get(self, day: date) -> SummaryResult:
        """The summary for day: stored, else from the provider, else a fallback."""
        async with self._lock:
            stored = await asyncio.to_thread(self._store.get, day)
            if stored is not None:
                return SummaryResult(summary=stored, provider=self._provider.name, cached=True)
            events = await self._events(day)
            if not events:
                return self._template(events, day)
            return await self._from_provider(events, day)

    async def cached(self, day: date) -> DailySummary | None:
        """The summary already stored for day, or None. Never calls the provider."""
        return await asyncio.to_thread(self._store.get, day)

    async def generate(self, day: date, *, refresh: bool = False) -> SummaryResult:
        """The summary for day, failing loudly: a provider failure raises SummaryUnavailableError.

        Unlike `get` it never falls back to an earlier summary or the template, so the caller can
        show the failure. With `refresh` the stored summary is ignored and replaced on success.
        """
        async with self._lock:
            if not refresh:
                stored = await asyncio.to_thread(self._store.get, day)
                if stored is not None:
                    return SummaryResult(summary=stored, provider=self._provider.name, cached=True)
            events = await self._events(day)
            if not events:
                return self._template(events, day)
            try:
                return await self._ask(events, day)
            except SummaryProviderError as exc:
                raise SummaryUnavailableError(self._log_failure(exc)) from None

    async def for_day(self, day: date) -> str | None:
        """The summary as plain text for the web page."""
        return summary_text((await self.get(day)).summary)

    async def _from_provider(self, events: list[Event], day: date) -> SummaryResult:
        try:
            return await self._ask(events, day)
        except SummaryProviderError as exc:
            self._log_failure(exc)
            return await self._fallback(events, day)

    async def _ask(self, events: list[Event], day: date) -> SummaryResult:
        prompt = build_prompt(events, self._include_email, day)
        summary = await self._provider.summarize(prompt)
        await asyncio.to_thread(self._store.put, day, summary)
        return SummaryResult(summary=summary, provider=self._provider.name, cached=False)

    def _log_failure(self, exc: SummaryProviderError) -> str:
        limited = isinstance(exc, SummaryRateLimited)
        logger.warning(
            "Summary provider %s %s: %s",
            self._provider.name,
            "rate limited" if limited else "failed",
            exc,
        )
        return "rate_limited" if limited else "failed"

    async def _fallback(self, events: list[Event], day: date) -> SummaryResult:
        earlier = await asyncio.to_thread(self._store.latest_before, day)
        if earlier is not None:
            return SummaryResult(summary=earlier, provider=PROVIDER_STORED, cached=True)
        return self._template(events, day)

    def _template(self, events: list[Event], day: date) -> SummaryResult:
        # Never stored: a failed day must retry the provider on the next request.
        return SummaryResult(
            summary=template_summary(events, day), provider=PROVIDER_TEMPLATE, cached=False
        )

    async def _events(self, day: date) -> list[Event]:
        """The day's events, plus what needs attention when day is today, in the local zone."""
        events = list(await self._agenda.day(day))
        if day == self._clock.now().astimezone(self._tz).date():
            seen = {event.id for event in events}
            events += [e for e in await self._agenda.attention() if e.id not in seen]
        if not self._include_email:
            events = [event for event in events if event.kind != "email"]
        return [self._localise(event) for event in events]

    def _localise(self, event: Event) -> Event:
        if event.due is None:
            return event
        return event.model_copy(update={"due": event.due.astimezone(self._tz)})
