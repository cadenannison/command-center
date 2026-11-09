"""Canvas reads: active courses, assignments, planner items and calendar events as `Event`s.

Every function takes an open `CanvasClient`; the adapter in `canvas.py` owns the session.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

from command_center.adapters.canvas_client import CanvasClient, Params
from command_center.adapters.canvas_models import (
    Assignment,
    CalendarEvent,
    Course,
    PlannerItem,
    parse_rows,
)
from command_center.core.errors import AuthExpired
from command_center.core.schema import Event, event_id
from command_center.core.windows import TimeWindow

# Named for the adapter, not this file: operators filter on it and a test pins it (decision 0081).
logger = logging.getLogger("command_center.adapters.canvas")

SOURCE = "canvas"
CONTEXT_CODE_LIMIT = 10  # Canvas ignores context_codes[] beyond ten.
_SUBMITTED_STATES = frozenset({"submitted", "graded", "pending_review"})
_COURSE_IN_PATH = re.compile(r"/courses/(\d+)(?:/|$)")


async def active_courses(canvas: CanvasClient) -> list[Course]:
    rows = await canvas.pages("/api/v1/courses", {"enrollment_state": "active"})
    courses = parse_rows(rows, Course, "courses")
    # Date-restricted courses refuse their content, which would fail the whole sync.
    return [course for course in courses if not course.access_restricted_by_date]


async def assignments(
    canvas: CanvasClient, course: Course, window: TimeWindow, fetched_at: datetime
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
    for assignment in parse_rows(rows, Assignment, "assignments"):
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


async def planner_events(
    canvas: CanvasClient,
    window: TimeWindow,
    bounds: Mapping[str, str],
    fetched_at: datetime,
    known_assignments: Sequence[Event] = (),
) -> list[Event]:
    rows = await canvas.pages("/api/v1/planner/items", bounds)
    listed = {(a.raw.get("course_id"), a.title, a.due) for a in known_assignments}
    events: list[Event] = []
    for item in parse_rows(rows, PlannerItem, "planner items"):
        # Assignments arrive per course with their submission state, so skip the planner's copy.
        if item.plannable_type == "assignment":
            continue
        plannable = item.plannable
        start = plannable.start_at or plannable.todo_date or plannable.due_at
        if start is None:
            continue
        title = plannable.title or "Untitled event"
        course_id = _course_id(item.html_url)
        # A graded quiz or discussion is also an assignment, and the planner links the two by no
        # documented field, so an item with an assignment's course, title and due instant is its
        # copy; with no course in its link, title and due instant alone decide (decision 0095).
        if (course_id, title, start) in listed or (
            course_id is None and any(key[1:] == (title, start) for key in listed)
        ):
            continue
        kind_key = f"{item.plannable_type}:{item.plannable_id}"
        event = _event(
            canvas,
            source_id=kind_key,
            title=title,
            start=start,
            end=plannable.end_at,
            html_url=item.html_url,
            fetched_at=fetched_at,
            raw={
                "plannable_type": item.plannable_type,
                "plannable_id": str(item.plannable_id),
                **({"course_id": course_id} if course_id is not None else {}),
            },
        )
        if _in_window(event, window):
            events.append(event)
    return events


async def calendar_events(
    canvas: CanvasClient,
    courses: Sequence[Course],
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
        for entry in parse_rows(rows, CalendarEvent, "calendar events"):
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


def _course_id(html_url: str | None) -> int | None:
    """The course a planner item belongs to, read from `/courses/<id>/...` in its link."""
    found = _COURSE_IN_PATH.search(html_url or "")
    return int(found.group(1)) if found else None


def _in_window(event: Event, window: TimeWindow) -> bool:
    """Match EventStore.query: spans by overlap, points by their start in [start, end)."""
    start = event.start or event.due
    if start is None:
        return False
    if event.end is not None and event.end > start:
        return start < window.end and event.end > window.start
    return window.contains(start)


def date_params(window: TimeWindow, lookback: timedelta) -> dict[str, str]:
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
