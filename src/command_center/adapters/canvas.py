"""Canvas LMS source: assignments, planner items and calendar events for the active courses."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from command_center.adapters.canvas_client import (
    CanvasClient,
    Params,
    Sleep,
    missing_credentials,
    open_canvas,
)
from command_center.core.errors import AuthExpired, FatalError, SourceError
from command_center.core.ports import Clock
from command_center.core.schema import Event, ValidationResult, event_id
from command_center.core.windows import TimeWindow

logger = logging.getLogger(__name__)

SOURCE = "canvas"
CONTEXT_CODE_LIMIT = 10  # Canvas ignores context_codes[] beyond ten.
DEFAULT_LOOKBACK_DAYS = 7
_SUBMITTED_STATES = frozenset({"submitted", "graded", "pending_review"})


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class _Course(_Model):
    id: int
    name: str | None = None
    course_code: str | None = None
    access_restricted_by_date: bool = False


class _Submission(_Model):
    workflow_state: str | None = None


class _Assignment(_Model):
    id: int
    name: str | None = None
    due_at: AwareDatetime | None = None
    html_url: str | None = None
    submission: _Submission | None = None


class _CalendarEvent(_Model):
    id: int
    title: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    html_url: str | None = None
    workflow_state: str | None = None


class _Plannable(_Model):
    title: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    todo_date: AwareDatetime | None = None
    due_at: AwareDatetime | None = None


class _PlannerItem(_Model):
    plannable_type: str
    plannable_id: str | int
    plannable: _Plannable
    html_url: str | None = None


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
        bounds = _date_params(window, self._lookback)
        async with open_canvas(creds, self._sleep) as canvas:
            courses = await _active_courses(canvas)
            for course in courses:
                for event in await _assignments(canvas, course, window, fetched_at):
                    events[event.id] = event
            for event in await _planner_events(canvas, window, bounds, fetched_at):
                events[event.id] = event
            # Calendar events go last: they carry an end, so they win over the planner's copy.
            for event in await _calendar_events(canvas, courses, window, bounds, fetched_at):
                events[event.id] = event
        return list(events.values())


async def _active_courses(canvas: CanvasClient) -> list[_Course]:
    rows = await canvas.pages("/api/v1/courses", {"enrollment_state": "active"})
    courses = _parse(rows, _Course, "courses")
    # Date-restricted courses refuse their content, which would fail the whole sync.
    return [course for course in courses if not course.access_restricted_by_date]


async def _assignments(
    canvas: CanvasClient, course: _Course, window: TimeWindow, fetched_at: datetime
) -> list[Event]:
    try:
        rows = await canvas.pages(
            f"/api/v1/courses/{course.id}/assignments", {"include[]": "submission"}
        )
    except AuthExpired as exc:
        # The one place a failure does not abort the fetch (decisions 0041, 0046): Canvas answers
        # 401 for a course the user may not read, so no access means no assignments from that
        # course, none of its pages. Its planner items and calendar events are still returned.
        logger.warning(
            "canvas course skipped: no access",
            extra={"source": SOURCE, "course_id": course.id, "reason": type(exc).__name__},
        )
        return []
    events: list[Event] = []
    for assignment in _parse(rows, _Assignment, "assignments"):
        if assignment.due_at is None or not window.contains(assignment.due_at):
            continue
        state = assignment.submission.workflow_state if assignment.submission else None
        events.append(
            Event(
                id=event_id(SOURCE, f"{course.id}:{assignment.id}"),
                source=SOURCE,
                kind="assignment",
                title=assignment.name or "Untitled assignment",
                due=assignment.due_at,
                link=_absolute(canvas, assignment.html_url),
                status="done" if state in _SUBMITTED_STATES else "open",
                raw={
                    "course_id": course.id,
                    "course_name": course.name,
                    "course_code": course.course_code,
                    "assignment_id": assignment.id,
                    "submission_state": state,
                },
                fetched_at=fetched_at,
            )
        )
    return events


async def _planner_events(
    canvas: CanvasClient, window: TimeWindow, bounds: Mapping[str, str], fetched_at: datetime
) -> list[Event]:
    rows = await canvas.pages("/api/v1/planner/items", bounds)
    events: list[Event] = []
    for item in _parse(rows, _PlannerItem, "planner items"):
        # Assignments arrive per course with their submission state, so skip the planner's copy.
        if item.plannable_type == "assignment":
            continue
        plannable = item.plannable
        start = plannable.start_at or plannable.todo_date or plannable.due_at
        if start is None:
            continue
        kind_key = f"{item.plannable_type}:{item.plannable_id}"
        event = _event(
            canvas,
            source_id=kind_key,
            title=plannable.title,
            start=start,
            end=plannable.end_at,
            html_url=item.html_url,
            fetched_at=fetched_at,
            raw={"plannable_type": item.plannable_type, "plannable_id": str(item.plannable_id)},
        )
        if _in_window(event, window):
            events.append(event)
    return events


async def _calendar_events(
    canvas: CanvasClient,
    courses: Sequence[_Course],
    window: TimeWindow,
    bounds: Mapping[str, str],
    fetched_at: datetime,
) -> list[Event]:
    # With no context_codes[] Canvas returns only the personal calendar, so course calendars
    # need their own calls, ten codes at a time.
    codes = [f"course_{course.id}" for course in courses]
    queries: list[Params] = [_calendar_params(bounds, None)]
    queries += [
        _calendar_params(bounds, codes[i : i + CONTEXT_CODE_LIMIT])
        for i in range(0, len(codes), CONTEXT_CODE_LIMIT)
    ]
    events: list[Event] = []
    for query in queries:
        rows = await canvas.pages("/api/v1/calendar_events", query)
        for entry in _parse(rows, _CalendarEvent, "calendar events"):
            if entry.start_at is None or entry.workflow_state == "deleted":
                continue
            event = _event(
                canvas,
                source_id=f"calendar_event:{entry.id}",
                title=entry.title,
                start=entry.start_at,
                end=entry.end_at,
                html_url=entry.html_url,
                fetched_at=fetched_at,
                raw={"plannable_type": "calendar_event", "plannable_id": str(entry.id)},
            )
            if _in_window(event, window):
                events.append(event)
    return events


def _event(  # noqa: PLR0913  (one call per source shape; keyword-only, all required)
    canvas: CanvasClient,
    *,
    source_id: str,
    title: str | None,
    start: datetime,
    end: datetime | None,
    html_url: str | None,
    fetched_at: datetime,
    raw: dict[str, object],
) -> Event:
    return Event(
        id=event_id(SOURCE, source_id),
        source=SOURCE,
        kind="event",
        title=title or "Untitled event",
        start=start,
        end=end,
        link=_absolute(canvas, html_url),
        raw=raw,
        fetched_at=fetched_at,
    )


def _in_window(event: Event, window: TimeWindow) -> bool:
    """Match EventStore.query: spans by overlap, points by their start in [start, end)."""
    start = event.start or event.due
    if start is None:
        return False
    if event.end is not None and event.end > start:
        return start < window.end and event.end > window.start
    return window.contains(start)


def _date_params(window: TimeWindow, lookback: timedelta) -> dict[str, str]:
    """Query bounds: Canvas may match on an item's start, so ask from `lookback` before the window.

    Canvas bounds are inclusive and the window is half-open, and the lookback fetches items
    outside the window on purpose; `_in_window` trims both (decision 0042).
    """
    return {"start_date": _iso(window.start - lookback), "end_date": _iso(window.end)}


def _calendar_params(bounds: Mapping[str, str], context_codes: list[str] | None) -> Params:
    params: dict[str, str | list[str]] = {
        "type": "event",
        "excludes[]": "description",
        **bounds,
    }
    if context_codes is not None:
        params["context_codes[]"] = context_codes
    return params


def _iso(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _absolute(canvas: CanvasClient, html_url: str | None) -> str | None:
    if not html_url:
        return None
    absolute = urljoin(f"{canvas.origin}/", html_url)
    return absolute if absolute.startswith("https://") else None


def _parse[M: _Model](rows: Sequence[object], model: type[M], what: str) -> list[M]:
    try:
        return [model.model_validate(row) for row in rows]
    except ValidationError:
        # The error text quotes the offending input, so it is dropped (decision 0023).
        msg = f"Failed to read Canvas {what}: the response had an unexpected shape"
        raise FatalError(msg) from None
