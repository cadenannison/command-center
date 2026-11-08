"""Shared setup for the Canvas adapter tests: fake DNS, a recording sleep, JSON shapes, routes.

The JSON shapes follow the Canvas REST docs (courses, assignments, planner, calendar_events);
fields the docs do not define are left out.
"""

import socket
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
import respx
from respx.models import Call

from command_center.adapters.canvas import CanvasAdapter
from command_center.core.windows import TimeWindow
from fakes import FakeClock

BASE = "https://canvas.school.edu"
TOKEN = "fake-canvas-token"  # noqa: S105  (made up; the tests assert it never leaks)
CREDS = {"base_url": BASE, "token": TOKEN}
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=datetime(2026, 11, 2, tzinfo=UTC), end=datetime(2026, 11, 9, tzinfo=UTC))

type Json = dict[str, object]


class RecordingSleep:
    """A sleep that returns at once and remembers how long it was asked to wait."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def stub_dns(monkeypatch: pytest.MonkeyPatch, address: str = "93.184.216.34") -> None:
    """Make every host resolve to address, so no test touches real DNS."""

    def resolve(_host: str, _port: object) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def make_adapter(
    sleep: RecordingSleep | None = None, *, lookback_days: int | None = None
) -> CanvasAdapter:
    """Build the adapter; lookback_days None keeps the adapter's own default."""
    clock, pause = FakeClock(NOW), sleep or RecordingSleep()
    if lookback_days is None:
        return CanvasAdapter(clock, sleep=pause)
    return CanvasAdapter(clock, sleep=pause, lookback_days=lookback_days)


def course(course_id: int = 7, **extra: object) -> Json:
    return {"id": course_id, "name": "Biology 101", "course_code": "BIO101", **extra}


def assignment(
    assignment_id: int = 42,
    due_at: str | None = "2026-11-04T06:59:00Z",
    state: str | None = None,
    course_id: int = 7,
) -> Json:
    row: Json = {
        "id": assignment_id,
        "name": "Lab report",
        "due_at": due_at,
        "html_url": f"{BASE}/courses/{course_id}/assignments/{assignment_id}",
    }
    if state is not None:
        row["submission"] = {"workflow_state": state}
    return row


def calendar_event(
    event_id: int = 5,
    start_at: str | None = "2026-11-05T15:00:00Z",
    end_at: str | None = "2026-11-05T16:00:00Z",
    workflow_state: str = "active",
) -> Json:
    return {
        "id": event_id,
        "title": "Office hours",
        "start_at": start_at,
        "end_at": end_at,
        "html_url": f"{BASE}/calendar?event_id={event_id}",
        "workflow_state": workflow_state,
    }


def planner_note(note_id: int = 9, todo_date: str = "2026-11-05T06:00:00Z") -> Json:
    return {
        "plannable_type": "planner_note",
        "plannable_id": str(note_id),
        "plannable": {"id": note_id, "title": "Buy textbook", "todo_date": todo_date},
        "html_url": None,
    }


def planner_topic(topic_id: int = 8, due_at: str | None = "2026-11-06T06:59:00Z") -> Json:
    return {
        "plannable_type": "discussion_topic",
        "plannable_id": str(topic_id),
        "plannable": {"id": topic_id, "title": "Week 3 discussion", "due_at": due_at},
        "html_url": f"/courses/7/discussion_topics/{topic_id}",
    }


def planner_calendar_event(
    event_id: int = 5,
    start_at: str = "2026-11-05T15:00:00Z",
    end_at: str | None = None,
) -> Json:
    return {
        "plannable_type": "calendar_event",
        "plannable_id": str(event_id),
        "plannable": {
            "id": event_id,
            "title": "Office hours",
            "start_at": start_at,
            "end_at": end_at,
        },
        "html_url": None,
    }


def planner_assignment(assignment_id: int = 42) -> Json:
    return {
        "plannable_type": "assignment",
        "plannable_id": str(assignment_id),
        "plannable": {"id": assignment_id, "due_at": "2026-11-04T06:59:00Z"},
        "html_url": f"{BASE}/courses/7/assignments/{assignment_id}",
    }


def link_next(url: str) -> dict[str, str]:
    return {"Link": f'<{url}>; rel="next"'}


def sent(router: respx.MockRouter) -> list[httpx.Request]:
    """Every request the router saw, in order (respx's CallList is untyped under pyright strict)."""
    calls: list[Call] = list(router.calls)  # pyright: ignore[reportUnknownArgumentType]
    return [call.request for call in calls]


def serve(  # noqa: PLR0913  (one keyword per endpoint the adapter reads)
    router: respx.MockRouter,
    *,
    courses: Sequence[Json] = (),
    assignments: Mapping[int, Sequence[Json]] | None = None,
    planner: Sequence[Json] = (),
    personal_calendar: Sequence[Json] = (),
    course_calendar: Sequence[Json] = (),
) -> None:
    """Register every endpoint the adapter reads; unlisted courses have no assignments."""
    router.get(f"{BASE}/api/v1/courses").respond(json=list(courses))
    for row in courses:
        course_id = row["id"]
        rows = (assignments or {}).get(int(str(course_id)), [])
        router.get(f"{BASE}/api/v1/courses/{course_id}/assignments").respond(json=list(rows))

    def planner_items(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_starting_from(planner, request))

    def calendar(request: httpx.Request) -> httpx.Response:
        scoped = bool(request.url.params.get_list("context_codes[]"))
        rows = course_calendar if scoped else personal_calendar
        return httpx.Response(200, json=_starting_from(rows, request))

    router.get(f"{BASE}/api/v1/planner/items").mock(side_effect=planner_items)
    router.get(f"{BASE}/api/v1/calendar_events").mock(side_effect=calendar)


def _starting_from(rows: Sequence[Json], request: httpx.Request) -> list[Json]:
    """Model Canvas at its strictest: only items starting on or after start_date come back.

    The docs do not say whether an item that began earlier but still runs is returned, so the
    mock assumes it is not; an adapter that wants such items must ask for an earlier start_date.
    """
    raw = request.url.params.get("start_date")
    if raw is None:
        return list(rows)
    floor = datetime.fromisoformat(raw)
    return [row for row in rows if (begin := _row_start(row)) is not None and begin >= floor]


def _row_start(row: Json) -> datetime | None:
    nested = row.get("plannable")
    fields = cast("Mapping[str, object]", nested) if isinstance(nested, dict) else row
    for key in ("start_at", "todo_date", "due_at"):
        value = fields.get(key)
        if isinstance(value, str):
            return datetime.fromisoformat(value)
    return None
