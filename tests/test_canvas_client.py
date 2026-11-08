"""Canvas transport behaviour seen through CanvasAdapter.fetch: pagination, backoff, errors."""

import logging
from collections.abc import Callable, Iterator

import httpx
import pytest
import respx

from canvas_support import (
    BASE,
    CREDS,
    TOKEN,
    WINDOW,
    RecordingSleep,
    assignment,
    course,
    link_next,
    make_adapter,
    sent,
    serve,
    stub_dns,
)
from command_center.adapters import canvas_client
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.schema import event_id

COURSES = f"{BASE}/api/v1/courses"
ASSIGNMENTS_7 = f"{BASE}/api/v1/courses/7/assignments"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_dns(monkeypatch)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _second_page(
    page_two: httpx.Response, first: list[dict[str, object]]
) -> Callable[[httpx.Request], httpx.Response]:
    """Answer page 1 with `first` and a Link to page 2, which answers `page_two`."""
    page_two_url = f"{ASSIGNMENTS_7}?page=2&per_page=100"

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return page_two
        return httpx.Response(200, json=first, headers=link_next(page_two_url))

    return answer


# ---------------------------------------------------------------- pagination


async def test_assignments_on_every_page_are_returned(router: respx.MockRouter) -> None:
    serve(router, courses=[course()])
    last = httpx.Response(200, json=[assignment(2, "2026-11-05T06:59:00Z")])
    router.get(ASSIGNMENTS_7).mock(
        side_effect=_second_page(last, [assignment(1, "2026-11-04T06:59:00Z")])
    )
    events = await make_adapter().fetch(CREDS, WINDOW)
    assert {e.id for e in events} == {event_id("canvas", "7:1"), event_id("canvas", "7:2")}


async def test_the_next_link_is_followed_exactly_as_canvas_gave_it(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course()])
    opaque = f"{ASSIGNMENTS_7}?page=bookmark:abc&per_page=100"
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(200, json=[], headers=link_next(opaque))
        return httpx.Response(200, json=[])

    router.get(ASSIGNMENTS_7).mock(side_effect=answer)
    _ = await make_adapter().fetch(CREDS, WINDOW)
    assert "per_page=100" in seen[0]
    assert seen[1] == str(httpx.URL(opaque))


async def test_the_course_list_is_paginated_too(router: respx.MockRouter) -> None:
    serve(router, courses=[course(8)])
    second = f"{COURSES}?page=2&per_page=100"

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[course(8)])
        return httpx.Response(200, json=[course(7)], headers=link_next(second))

    router.get(COURSES).mock(side_effect=answer)
    router.get(ASSIGNMENTS_7).respond(json=[assignment()])
    router.get(f"{BASE}/api/v1/courses/8/assignments").respond(json=[assignment(43, course_id=8)])
    events = await make_adapter().fetch(CREDS, WINDOW)
    assert len(events) == 2


async def test_a_link_to_another_host_is_refused_before_any_request_is_sent(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course()])
    evil = router.get("https://evil.example/api/v1/courses/7/assignments?page=2")
    router.get(ASSIGNMENTS_7).respond(
        json=[], headers=link_next("https://evil.example/api/v1/courses/7/assignments?page=2")
    )
    with pytest.raises(FatalError, match="leaves the Canvas host"):
        await make_adapter().fetch(CREDS, WINDOW)
    assert not evil.called


async def test_a_link_downgraded_to_http_is_refused(router: respx.MockRouter) -> None:
    serve(router, courses=[course()])
    router.get(ASSIGNMENTS_7).respond(
        json=[], headers=link_next("http://canvas.school.edu/api/v1/courses/7/assignments?page=2")
    )
    with pytest.raises(FatalError, match="leaves the Canvas host"):
        await make_adapter().fetch(CREDS, WINDOW)


@pytest.mark.parametrize(
    "next_url",
    [
        "https://canvas.school.edu:99999/api/v1/courses/7/assignments?page=2",
        "https://canvas.school.edu:abc/api/v1/courses/7/assignments?page=2",
        "https://[::1/api/v1/courses/7/assignments?page=2",
    ],
)
async def test_a_malformed_next_link_raises_fatal_error_not_a_bare_value_error(
    router: respx.MockRouter, next_url: str
) -> None:
    serve(router, courses=[course()])
    router.get(ASSIGNMENTS_7).respond(json=[], headers=link_next(next_url))
    with pytest.raises(FatalError, match="leaves the Canvas host"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_next_link_that_repeats_a_page_is_refused(router: respx.MockRouter) -> None:
    serve(router, courses=[course()])
    again = f"{ASSIGNMENTS_7}?page=2&per_page=100"
    router.get(ASSIGNMENTS_7).respond(json=[], headers=link_next(again))
    with pytest.raises(FatalError, match="repeats a page"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_pagination_stops_at_the_page_cap(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canvas_client, "MAX_PAGES", 3)
    serve(router, courses=[course()])

    def endless(request: httpx.Request) -> httpx.Response:
        number = int(request.url.params.get("page", "1")) + 1
        return httpx.Response(
            200, json=[], headers=link_next(f"{ASSIGNMENTS_7}?page={number}&per_page=100")
        )

    router.get(ASSIGNMENTS_7).mock(side_effect=endless)
    with pytest.raises(FatalError, match="more than 3 pages"):
        await make_adapter().fetch(CREDS, WINDOW)


# ---------------------------------------------------------------- auth


async def test_a_401_raises_auth_expired_without_the_token_in_the_message(
    router: respx.MockRouter,
) -> None:
    router.get(COURSES).respond(401)
    with pytest.raises(AuthExpired, match=r"token rejected \(401\)") as caught:
        await make_adapter().fetch(CREDS, WINDOW)
    assert TOKEN not in str(caught.value)


async def test_a_401_on_one_courses_assignments_skips_only_that_course(
    router: respx.MockRouter,
) -> None:
    serve(
        router,
        courses=[course(7), course(8), course(9)],
        assignments={7: [assignment(1)], 9: [assignment(3, course_id=9)]},
    )
    router.get(f"{BASE}/api/v1/courses/8/assignments").respond(401)
    events = await make_adapter().fetch(CREDS, WINDOW)
    assert {e.id for e in events} == {event_id("canvas", "7:1"), event_id("canvas", "9:3")}


async def test_a_401_on_a_later_page_drops_the_whole_course_not_just_the_rest(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course(7), course(8)], assignments={8: [assignment(2, course_id=8)]})
    router.get(ASSIGNMENTS_7).mock(side_effect=_second_page(httpx.Response(401), [assignment(1)]))
    events = await make_adapter().fetch(CREDS, WINDOW)
    assert [e.id for e in events] == [event_id("canvas", "8:2")]


async def test_a_skipped_course_is_logged_by_id_and_error_class_without_a_url_or_token(
    router: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    serve(router, courses=[course(7)])
    router.get(ASSIGNMENTS_7).respond(401)
    with caplog.at_level(logging.WARNING, logger="command_center.adapters.canvas"):
        _ = await make_adapter().fetch(CREDS, WINDOW)
    [record] = [r for r in caplog.records if r.name == "command_center.adapters.canvas"]
    assert (record.__dict__["course_id"], record.__dict__["reason"]) == (7, "AuthExpired")
    assert "canvas.school.edu" not in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("endpoint", ["planner/items", "calendar_events"])
async def test_a_401_on_planner_or_calendar_still_raises_auth_expired(
    router: respx.MockRouter, endpoint: str
) -> None:
    serve(router, courses=[course(7)])
    router.get(f"{BASE}/api/v1/{endpoint}").respond(401)
    with pytest.raises(AuthExpired):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_401_on_a_later_page_of_the_course_list_still_raises_auth_expired(
    router: respx.MockRouter,
) -> None:
    second = f"{COURSES}?page=2&per_page=100"

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(401)
        return httpx.Response(200, json=[course(7)], headers=link_next(second))

    router.get(COURSES).mock(side_effect=answer)
    router.get(ASSIGNMENTS_7).respond(json=[assignment()])
    with pytest.raises(AuthExpired):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_401_on_a_course_scoped_calendar_query_still_raises_auth_expired(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course(7)])

    def calendar(request: httpx.Request) -> httpx.Response:
        if request.url.params.get_list("context_codes[]"):
            return httpx.Response(401)
        return httpx.Response(200, json=[])

    router.get(f"{BASE}/api/v1/calendar_events").mock(side_effect=calendar)
    with pytest.raises(AuthExpired):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_403_on_one_course_is_still_throttling_not_a_skip(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course(7)])
    router.get(ASSIGNMENTS_7).respond(403)
    with pytest.raises(TransientError, match="rate limited"):
        await make_adapter().fetch(CREDS, WINDOW)


@pytest.mark.parametrize("missing", ["base_url", "token"])
async def test_incomplete_credentials_raise_auth_expired(
    router: respx.MockRouter, missing: str
) -> None:
    with pytest.raises(AuthExpired):
        await make_adapter().fetch({k: v for k, v in CREDS.items() if k != missing}, WINDOW)
    assert router.calls.call_count == 0


# ---------------------------------------------------------------- rate limits


@pytest.mark.parametrize("status", [429, 403])
async def test_a_throttled_request_is_retried_after_a_backoff(
    router: respx.MockRouter, status: int
) -> None:
    serve(router, courses=[course()], assignments={7: [assignment()]})
    replies = iter([httpx.Response(status), httpx.Response(200, json=[course()])])

    def answer(_request: httpx.Request) -> httpx.Response:
        return next(replies)

    router.get(COURSES).mock(side_effect=answer)
    sleep = RecordingSleep()
    events = await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == [2.0]
    assert len(events) == 1


@pytest.mark.parametrize("status", [429, 403])
async def test_a_request_throttled_past_the_cap_raises_transient_error(
    router: respx.MockRouter, status: int
) -> None:
    route = router.get(COURSES).respond(status)
    sleep = RecordingSleep()
    with pytest.raises(TransientError, match=rf"rate limited \({status}\) after 3 retries"):
        await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == [2.0, 4.0, 8.0]
    assert route.call_count == 4


async def test_retry_after_sets_the_backoff_up_to_a_ceiling(router: respx.MockRouter) -> None:
    router.get(COURSES).respond(429, headers={"Retry-After": "600"})
    sleep = RecordingSleep()
    with pytest.raises(TransientError):
        await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == [30.0, 30.0, 30.0]


async def test_a_low_rate_limit_quota_pauses_before_the_next_request(
    router: respx.MockRouter,
) -> None:
    router.get(COURSES).respond(json=[], headers={"X-Rate-Limit-Remaining": "12.5"})
    router.get(f"{BASE}/api/v1/planner/items").respond(json=[])
    router.get(f"{BASE}/api/v1/calendar_events").respond(json=[])
    sleep = RecordingSleep()
    assert await make_adapter(sleep).fetch(CREDS, WINDOW) == []
    assert sleep.delays == [2.0]


async def test_a_healthy_quota_does_not_pause(router: respx.MockRouter) -> None:
    serve(router)
    router.get(COURSES).respond(json=[], headers={"X-Rate-Limit-Remaining": "600"})
    sleep = RecordingSleep()
    _ = await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == []


# ---------------------------------------------------------------- failure mid-pagination


async def test_a_server_error_on_page_two_raises_instead_of_returning_page_one(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course()])
    router.get(ASSIGNMENTS_7).mock(side_effect=_second_page(httpx.Response(500), [assignment(1)]))
    with pytest.raises(TransientError, match=r"server error \(500\)"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_throttling_that_persists_on_page_two_raises_transient_error(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course()])
    router.get(ASSIGNMENTS_7).mock(side_effect=_second_page(httpx.Response(429), [assignment(1)]))
    with pytest.raises(TransientError, match="rate limited"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_timeout_on_page_two_raises_transient_error(router: respx.MockRouter) -> None:
    serve(router, courses=[course()])

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            msg = "slow"
            raise httpx.ReadTimeout(msg, request=request)
        return httpx.Response(
            200, json=[assignment(1)], headers=link_next(f"{ASSIGNMENTS_7}?page=2&per_page=100")
        )

    router.get(ASSIGNMENTS_7).mock(side_effect=answer)
    with pytest.raises(TransientError, match="timed out"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_failure_in_a_later_course_raises_instead_of_returning_the_first(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course(7), course(8)], assignments={7: [assignment()]})
    router.get(f"{BASE}/api/v1/courses/8/assignments").respond(502)
    with pytest.raises(TransientError):
        await make_adapter().fetch(CREDS, WINDOW)


# ---------------------------------------------------------------- other failures


async def test_a_server_error_raises_transient_error(router: respx.MockRouter) -> None:
    router.get(COURSES).respond(503)
    with pytest.raises(TransientError, match=r"server error \(503\)"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_connection_failure_raises_transient_error(router: respx.MockRouter) -> None:
    router.get(COURSES).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TransientError, match="Failed to reach Canvas: ConnectError"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_an_unexpected_client_error_raises_fatal_error(router: respx.MockRouter) -> None:
    router.get(COURSES).respond(404)
    with pytest.raises(FatalError, match=r"unexpected status \(404\)"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_a_redirect_is_not_followed(router: respx.MockRouter) -> None:
    elsewhere = router.get("https://evil.example/api/v1/courses")
    router.get(COURSES).respond(302, headers={"Location": "https://evil.example/api/v1/courses"})
    with pytest.raises(FatalError, match=r"unexpected status \(302\)"):
        await make_adapter().fetch(CREDS, WINDOW)
    assert not elsewhere.called


@pytest.mark.parametrize("body", [b"<html>", b'{"id": 1}'])
async def test_a_body_that_is_not_a_json_list_raises_fatal_error(
    router: respx.MockRouter, body: bytes
) -> None:
    router.get(COURSES).respond(content=body)
    with pytest.raises(FatalError, match="not a JSON list"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_an_unexpected_item_shape_raises_fatal_error_without_echoing_it(
    router: respx.MockRouter,
) -> None:
    router.get(COURSES).respond(json=[{"id": "not-a-number-secret"}])
    with pytest.raises(FatalError, match="unexpected shape") as caught:
        await make_adapter().fetch(CREDS, WINDOW)
    assert "secret" not in str(caught.value)


async def test_a_naive_due_date_raises_fatal_error(router: respx.MockRouter) -> None:
    serve(router, courses=[course()], assignments={7: [assignment(due_at="2026-11-04T06:59:00")]})
    with pytest.raises(FatalError, match="unexpected shape"):
        await make_adapter().fetch(CREDS, WINDOW)


# ---------------------------------------------------------------- guards and timeouts


async def test_a_host_resolving_privately_raises_fatal_error_before_any_request(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_dns(monkeypatch, "192.168.1.10")
    with pytest.raises(FatalError, match="Invalid Canvas URL"):
        await make_adapter().fetch(CREDS, WINDOW)
    assert router.calls.call_count == 0


async def test_a_dns_lookup_timeout_propagates_as_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow(_host: str) -> None:
        msg = "host lookup timed out"
        raise TransientError(msg)

    monkeypatch.setattr(canvas_client, "ensure_public_host", slow)
    with pytest.raises(TransientError, match="lookup timed out"):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_every_request_carries_an_explicit_timeout_and_the_bearer_token(
    router: respx.MockRouter,
) -> None:
    serve(router, courses=[course()])
    _ = await make_adapter().fetch(CREDS, WINDOW)
    requests = sent(router)
    assert requests
    for request in requests:
        timeout: dict[str, float | None] = request.extensions["timeout"]
        assert all(value is not None for value in timeout.values())
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
