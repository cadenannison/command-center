"""CanvasAdapter validation and mapping, with Canvas mocked by respx and DNS stubbed."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from canvas_support import (
    BASE,
    CREDS,
    NOW,
    TOKEN,
    WINDOW,
    assignment,
    calendar_event,
    course,
    make_adapter,
    planner_assignment,
    planner_calendar_event,
    planner_note,
    planner_topic,
    sent,
    serve,
    stub_dns,
)
from command_center.adapters import canvas_client
from command_center.core.errors import TransientError
from command_center.core.schema import event_id
from command_center.core.windows import TimeWindow


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_dns(monkeypatch)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


# ---------------------------------------------------------------- validate


async def test_validate_accepts_a_token_canvas_accepts(router: respx.MockRouter) -> None:
    route = router.get(f"{BASE}/api/v1/users/self").respond(json={"id": 1})
    result = await make_adapter().validate(CREDS)
    assert result.ok is True
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_validate_reports_a_rejected_token_as_a_message(router: respx.MockRouter) -> None:
    router.get(f"{BASE}/api/v1/users/self").respond(401)
    result = await make_adapter().validate(CREDS)
    assert (result.ok, result.message) == (False, "Token rejected")


async def test_validate_turns_a_network_error_into_a_message(router: respx.MockRouter) -> None:
    router.get(f"{BASE}/api/v1/users/self").mock(side_effect=httpx.ConnectError("refused"))
    result = await make_adapter().validate(CREDS)
    assert result.ok is False
    assert "Failed to reach Canvas" in result.message
    assert TOKEN not in result.message


async def test_validate_turns_a_timeout_into_a_message(router: respx.MockRouter) -> None:
    router.get(f"{BASE}/api/v1/users/self").mock(side_effect=httpx.ReadTimeout("slow"))
    result = await make_adapter().validate(CREDS)
    assert (result.ok, "timed out" in result.message) == (False, True)


async def test_validate_rejects_a_plain_http_url_without_sending_anything(
    router: respx.MockRouter,
) -> None:
    result = await make_adapter().validate({**CREDS, "base_url": "http://canvas.school.edu"})
    assert result.ok is False
    assert "Invalid Canvas URL" in result.message
    assert router.calls.call_count == 0


async def test_validate_rejects_a_host_that_resolves_privately_without_sending_anything(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_dns(monkeypatch, "10.0.0.5")
    result = await make_adapter().validate(CREDS)
    assert result.ok is False
    assert "Invalid Canvas URL" in result.message
    assert router.calls.call_count == 0


async def test_validate_turns_a_dns_timeout_into_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow(_host: str) -> None:
        msg = "host lookup timed out"
        raise TransientError(msg)

    monkeypatch.setattr(canvas_client, "ensure_public_host", slow)
    result = await make_adapter().validate(CREDS)
    assert (result.ok, result.message) == (False, "host lookup timed out")


@pytest.mark.parametrize("missing", ["base_url", "token"])
async def test_validate_asks_for_both_credentials(router: respx.MockRouter, missing: str) -> None:
    result = await make_adapter().validate({k: v for k, v in CREDS.items() if k != missing})
    assert (result.ok, router.calls.call_count) == (False, 0)


async def test_validate_strips_the_path_from_the_base_url(router: respx.MockRouter) -> None:
    route = router.get(f"{BASE}/api/v1/users/self").respond(json={"id": 1})
    result = await make_adapter().validate({**CREDS, "base_url": f"{BASE}/courses/7?tab=1"})
    assert result.ok is True
    assert route.called


# ---------------------------------------------------------------- assignments


async def test_an_open_assignment_maps_to_an_assignment_event(router: respx.MockRouter) -> None:
    serve(router, courses=[course()], assignments={7: [assignment()]})
    events = await make_adapter().fetch(CREDS, WINDOW)
    assert len(events) == 1
    [event] = events
    assert event.id == event_id("canvas", "7:42")
    assert (event.source, event.kind, event.title) == ("canvas", "assignment", "Lab report")
    assert event.due == datetime(2026, 11, 4, 6, 59, tzinfo=UTC)
    assert (event.start, event.end, event.urgency) == (None, None, 0)
    assert (event.status, event.link) == ("open", f"{BASE}/courses/7/assignments/42")
    assert event.fetched_at == NOW


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ("submitted", "done"),
        ("graded", "done"),
        ("pending_review", "done"),
        ("unsubmitted", "open"),
        (None, "open"),
    ],
)
async def test_assignment_status_follows_the_submission_state(
    router: respx.MockRouter, state: str | None, status: str
) -> None:
    serve(router, courses=[course()], assignments={7: [assignment(state=state)]})
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.status == status


async def test_assignments_are_requested_with_their_submission(router: respx.MockRouter) -> None:
    serve(router, courses=[course()], assignments={7: []})
    _ = await make_adapter().fetch(CREDS, WINDOW)
    request = next(r for r in sent(router) if r.url.path.endswith("assignments"))
    assert request.url.params.get_list("include[]") == ["submission"]
    assert request.url.params["per_page"] == "100"


async def test_an_undated_assignment_is_left_out(router: respx.MockRouter) -> None:
    serve(router, courses=[course()], assignments={7: [assignment(due_at=None)]})
    assert await make_adapter().fetch(CREDS, WINDOW) == []


@pytest.mark.parametrize(
    ("due_at", "expected_count"),
    [
        ("2026-11-02T00:00:00Z", 1),
        ("2026-11-08T23:59:59Z", 1),
        ("2026-11-01T23:59:59Z", 0),
        ("2026-11-09T00:00:00Z", 0),
    ],
)
async def test_assignments_are_kept_by_the_half_open_window(
    router: respx.MockRouter, due_at: str, expected_count: int
) -> None:
    serve(router, courses=[course()], assignments={7: [assignment(due_at=due_at)]})
    assert len(await make_adapter().fetch(CREDS, WINDOW)) == expected_count


async def test_event_raw_holds_public_item_fields_only(router: respx.MockRouter) -> None:
    serve(router, courses=[course()], assignments={7: [assignment(state="submitted")]})
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.raw == {
        "course_id": 7,
        "course_name": "Biology 101",
        "course_code": "BIO101",
        "assignment_id": 42,
        "submission_state": "submitted",
    }
    assert TOKEN not in repr(event)


async def test_a_date_restricted_course_is_skipped(router: respx.MockRouter) -> None:
    serve(router, courses=[course(7), course(8, access_restricted_by_date=True)])
    _ = await make_adapter().fetch(CREDS, WINDOW)
    paths = [r.url.path for r in sent(router)]
    assert "/api/v1/courses/8/assignments" not in paths
    assert "/api/v1/courses/7/assignments" in paths


# ---------------------------------------------------------------- planner and calendar


async def test_a_planner_note_maps_to_an_event_starting_at_its_todo_date(
    router: respx.MockRouter,
) -> None:
    serve(router, planner=[planner_note()])
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.id == event_id("canvas", "planner_note:9")
    assert (event.kind, event.title, event.status) == ("event", "Buy textbook", None)
    assert (event.start, event.end) == (datetime(2026, 11, 5, 6, tzinfo=UTC), None)


async def test_a_planner_assignment_is_left_to_the_course_fetch(router: respx.MockRouter) -> None:
    serve(
        router,
        courses=[course()],
        assignments={7: [assignment(state="submitted")]},
        planner=[planner_assignment()],
    )
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert (event.kind, event.status) == ("assignment", "done")


async def test_a_relative_planner_link_is_resolved_against_the_canvas_origin(
    router: respx.MockRouter,
) -> None:
    serve(router, planner=[planner_topic()])
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.link == f"{BASE}/courses/7/discussion_topics/8"


async def test_a_planner_item_without_a_date_is_left_out(router: respx.MockRouter) -> None:
    serve(router, planner=[planner_topic(due_at=None)])
    assert await make_adapter().fetch(CREDS, WINDOW) == []


async def test_a_planner_item_outside_the_window_is_left_out(router: respx.MockRouter) -> None:
    serve(router, planner=[planner_note(todo_date="2026-11-09T00:00:00Z")])
    assert await make_adapter().fetch(CREDS, WINDOW) == []


async def test_a_calendar_event_maps_to_an_event_with_start_and_end(
    router: respx.MockRouter,
) -> None:
    serve(router, personal_calendar=[calendar_event()])
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.id == event_id("canvas", "calendar_event:5")
    assert (event.kind, event.title) == ("event", "Office hours")
    assert event.start == datetime(2026, 11, 5, 15, tzinfo=UTC)
    assert event.end == datetime(2026, 11, 5, 16, tzinfo=UTC)
    assert event.link == f"{BASE}/calendar?event_id=5"


async def test_a_calendar_event_that_began_before_the_window_is_kept_by_overlap(
    router: respx.MockRouter,
) -> None:
    spanning = calendar_event(start_at="2026-10-31T00:00:00Z", end_at="2026-11-03T00:00:00Z")
    serve(router, personal_calendar=[spanning])
    assert len(await make_adapter().fetch(CREDS, WINDOW)) == 1


@pytest.mark.parametrize(
    "entry",
    [
        calendar_event(start_at="2026-11-09T00:00:00Z", end_at="2026-11-09T01:00:00Z"),
        calendar_event(start_at="2026-11-01T00:00:00Z", end_at="2026-11-02T00:00:00Z"),
        calendar_event(start_at=None, end_at=None),
        calendar_event(workflow_state="deleted"),
    ],
)
async def test_calendar_events_outside_the_window_or_undated_or_deleted_are_left_out(
    router: respx.MockRouter, entry: dict[str, object]
) -> None:
    serve(router, personal_calendar=[entry])
    assert await make_adapter().fetch(CREDS, WINDOW) == []


async def test_an_event_in_both_planner_and_calendar_is_returned_once_with_its_end(
    router: respx.MockRouter,
) -> None:
    serve(
        router,
        courses=[course()],
        planner=[planner_calendar_event()],
        course_calendar=[calendar_event()],
    )
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.end == datetime(2026, 11, 5, 16, tzinfo=UTC)


async def test_course_calendars_are_asked_for_ten_codes_at_a_time(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course(n) for n in range(1, 12)])
    _ = await make_adapter().fetch(CREDS, WINDOW)
    calls = [r for r in sent(router) if r.url.path.endswith("calendar_events")]
    scoped = [r.url.params.get_list("context_codes[]") for r in calls]
    assert [len(codes) for codes in scoped] == [0, 10, 1]
    assert scoped[2] == ["course_11"]


async def test_planner_and_calendar_are_asked_for_the_window_converted_to_utc(
    router: respx.MockRouter,
) -> None:
    chicago = ZoneInfo("America/Chicago")  # UTC-6 in November, so local midnight is 06:00Z
    window = TimeWindow(
        start=datetime(2026, 11, 2, tzinfo=chicago), end=datetime(2026, 11, 9, tzinfo=chicago)
    )
    serve(router)
    _ = await make_adapter(lookback_days=0).fetch(CREDS, window)
    bounded = [r for r in sent(router) if r.url.path.endswith(("planner/items", "calendar_events"))]
    assert len(bounded) >= 2
    for request in bounded:
        params = request.url.params
        assert (params["start_date"], params["end_date"]) == (
            "2026-11-02T06:00:00Z",
            "2026-11-09T06:00:00Z",
        )


@pytest.mark.parametrize(
    ("lookback_days", "start_date"),
    [
        (None, "2026-10-26T00:00:00Z"),
        (2, "2026-10-31T00:00:00Z"),
        (0, "2026-11-02T00:00:00Z"),
    ],
)
async def test_start_date_reaches_back_lookback_days_before_the_window(
    router: respx.MockRouter, lookback_days: int | None, start_date: str
) -> None:
    serve(router)
    _ = await make_adapter(lookback_days=lookback_days).fetch(CREDS, WINDOW)
    bounded = [r for r in sent(router) if r.url.path.endswith(("planner/items", "calendar_events"))]
    assert len(bounded) >= 2
    for request in bounded:
        params = request.url.params
        assert (params["start_date"], params["end_date"]) == (start_date, "2026-11-09T00:00:00Z")


async def test_a_calendar_event_that_began_five_days_before_the_window_and_still_runs_is_kept(
    router: respx.MockRouter,
) -> None:
    running = calendar_event(start_at="2026-10-28T09:00:00Z", end_at="2026-11-03T09:00:00Z")
    serve(router, personal_calendar=[running])
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.start == datetime(2026, 10, 28, 9, tzinfo=UTC)


async def test_a_calendar_event_that_ended_before_the_window_is_not_kept(
    router: respx.MockRouter,
) -> None:
    over = calendar_event(start_at="2026-10-27T09:00:00Z", end_at="2026-10-30T09:00:00Z")
    serve(router, personal_calendar=[over])
    assert await make_adapter().fetch(CREDS, WINDOW) == []


async def test_a_planner_event_that_began_five_days_before_the_window_and_still_runs_is_kept(
    router: respx.MockRouter,
) -> None:
    running = planner_calendar_event(start_at="2026-10-28T09:00:00Z", end_at="2026-11-03T09:00:00Z")
    serve(router, planner=[running])
    [event] = await make_adapter().fetch(CREDS, WINDOW)
    assert event.end == datetime(2026, 11, 3, 9, tzinfo=UTC)


async def test_a_planner_event_that_ended_before_the_window_is_not_kept(
    router: respx.MockRouter,
) -> None:
    over = planner_calendar_event(start_at="2026-10-27T09:00:00Z", end_at="2026-10-30T09:00:00Z")
    serve(router, planner=[over])
    assert await make_adapter().fetch(CREDS, WINDOW) == []


async def test_a_longer_lookback_keeps_an_event_that_began_ten_days_before(
    router: respx.MockRouter,
) -> None:
    long_running = calendar_event(start_at="2026-10-23T09:00:00Z", end_at="2026-11-03T09:00:00Z")
    serve(router, personal_calendar=[long_running])
    assert len(await make_adapter(lookback_days=14).fetch(CREDS, WINDOW)) == 1


async def test_a_negative_lookback_counts_as_zero(router: respx.MockRouter) -> None:
    serve(router)
    _ = await make_adapter(lookback_days=-3).fetch(CREDS, WINDOW)
    bounded = [r for r in sent(router) if r.url.path.endswith(("planner/items", "calendar_events"))]
    assert len(bounded) >= 2
    assert {r.url.params["start_date"] for r in bounded} == {"2026-11-02T00:00:00Z"}


async def test_a_planner_point_exactly_at_the_window_start_is_kept(
    router: respx.MockRouter,
) -> None:
    serve(router, planner=[planner_note(todo_date="2026-11-02T00:00:00Z")])
    assert len(await make_adapter().fetch(CREDS, WINDOW)) == 1


async def test_a_calendar_point_exactly_at_the_window_start_is_kept(
    router: respx.MockRouter,
) -> None:
    point = calendar_event(start_at="2026-11-02T00:00:00Z", end_at=None)
    serve(router, personal_calendar=[point])
    assert len(await make_adapter().fetch(CREDS, WINDOW)) == 1


@pytest.mark.parametrize(
    ("start_at", "end_at"),
    [
        ("2026-11-01T12:00:00Z", "2026-11-01T12:00:00Z"),  # zero length: a point before the window
        ("2026-11-01T12:00:00Z", "2026-11-01T11:00:00Z"),  # ends before it starts: still a point
    ],
)
async def test_a_calendar_item_that_does_not_end_after_it_starts_is_a_point_and_left_out_early(
    router: respx.MockRouter, start_at: str, end_at: str
) -> None:
    serve(router, personal_calendar=[calendar_event(start_at=start_at, end_at=end_at)])
    assert await make_adapter().fetch(CREDS, WINDOW) == []


async def test_a_zero_length_calendar_item_at_the_window_start_is_kept_as_a_point(
    router: respx.MockRouter,
) -> None:
    same = "2026-11-02T00:00:00Z"
    serve(router, personal_calendar=[calendar_event(start_at=same, end_at=same)])
    assert len(await make_adapter().fetch(CREDS, WINDOW)) == 1


async def test_the_next_course_is_not_requested_until_the_previous_one_has_answered(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course(7), course(8)])
    log: list[str] = []

    def answering(course_id: int) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
        async def answer(_request: httpx.Request) -> httpx.Response:
            log.append(f"start {course_id}")
            await asyncio.sleep(0)  # a yield point: concurrent fetches would interleave here
            log.append(f"end {course_id}")
            return httpx.Response(200, json=[])

        return answer

    for course_id in (7, 8):
        router.get(f"{BASE}/api/v1/courses/{course_id}/assignments").mock(
            side_effect=answering(course_id)
        )
    _ = await make_adapter().fetch(CREDS, WINDOW)
    assert log == ["start 7", "end 7", "start 8", "end 8"]
