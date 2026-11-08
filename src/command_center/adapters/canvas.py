"""Canvas LMS source: assignments, planner items and calendar events for the active courses."""

import asyncio
from collections.abc import Mapping
from datetime import timedelta

from command_center.adapters.canvas_client import Sleep, missing_credentials, open_canvas
from command_center.adapters.canvas_fetch import (
    SOURCE,
    active_courses,
    assignments,
    calendar_events,
    date_params,
    planner_events,
)
from command_center.core.errors import AuthExpired, SourceError
from command_center.core.ports import Clock
from command_center.core.schema import Event, ValidationResult
from command_center.core.windows import TimeWindow

DEFAULT_LOOKBACK_DAYS = 7


class CanvasAdapter:
    """SourceAdapter for Canvas (personal access token); decisions 0032, 0033, 0041, 0042."""

    def __init__(
        self,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        # A negative value would shrink the query below the window and lose events.
        self._lookback = timedelta(days=max(lookback_days, 0))

    @property
    def name(self) -> str:
        """The source name stored on every Event: "canvas"."""
        return SOURCE

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Check the token with GET /api/v1/users/self; failures become a message."""
        problem = missing_credentials(creds)
        if problem is not None:
            return ValidationResult(ok=False, message=problem)
        try:
            async with open_canvas(creds, self._sleep) as canvas:
                _ = await canvas.get("/api/v1/users/self")
        except AuthExpired:
            return ValidationResult(ok=False, message="Token rejected")
        except SourceError as exc:
            return ValidationResult(ok=False, message=str(exc))
        return ValidationResult(ok=True, message="Connected to Canvas")

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        """Return the window's assignments, planner items and calendar events, or raise."""
        fetched_at = self._clock.now()
        events: dict[str, Event] = {}
        bounds = date_params(window, self._lookback)
        async with open_canvas(creds, self._sleep) as canvas:
            courses = await active_courses(canvas)
            for course in courses:
                for event in await assignments(canvas, course, window, fetched_at):
                    events[event.id] = event
            for event in await planner_events(canvas, window, bounds, fetched_at):
                events[event.id] = event
            # Calendar events go last: they carry an end, so they win over the planner's copy.
            for event in await calendar_events(canvas, courses, window, bounds, fetched_at):
                events[event.id] = event
        return list(events.values())
