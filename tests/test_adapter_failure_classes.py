"""Permanent failures are not reported as transient (audit card 05, decision 0410)."""

import logging
from collections.abc import Iterator

import pytest
import respx
from caldav.lib.error import AuthorizationError, DAVError, NotFoundError

from canvas_support import BASE, CREDS, WINDOW, RecordingSleep, make_adapter, stub_dns
from command_center.core.errors import AuthExpired, FatalError, TransientError
from test_caldav_apple import CREDS as CALDAV_CREDS
from test_caldav_apple import WINDOW as CALDAV_WINDOW
from test_caldav_apple import FakeSession, adapter_for

COURSES = f"{BASE}/api/v1/courses"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_dns(monkeypatch)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


# ---------------------------------------------------------------- Canvas


async def test_a_bare_canvas_403_is_fatal_and_never_retried(router: respx.MockRouter) -> None:
    route = router.get(COURSES).respond(403, text="user not authorized")
    sleep = RecordingSleep()
    with pytest.raises(FatalError, match="Canvas refused this request"):
        await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == []
    assert route.call_count == 1


async def test_a_canvas_403_with_the_rate_limit_marker_is_retried_then_transient(
    router: respx.MockRouter,
) -> None:
    route = router.get(COURSES).respond(403, text="403 Forbidden (Rate Limit Exceeded)")
    sleep = RecordingSleep()
    with pytest.raises(TransientError, match="rate limited"):
        await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == [2.0, 4.0, 8.0]
    assert route.call_count == 4


async def test_a_canvas_429_without_a_body_is_still_throttled(router: respx.MockRouter) -> None:
    _ = router.get(COURSES).respond(429)
    sleep = RecordingSleep()
    with pytest.raises(TransientError, match="rate limited"):
        await make_adapter(sleep).fetch(CREDS, WINDOW)
    assert sleep.delays == [2.0, 4.0, 8.0]


async def test_a_canvas_401_is_still_auth_expired(router: respx.MockRouter) -> None:
    _ = router.get(COURSES).respond(401)
    with pytest.raises(AuthExpired):
        await make_adapter().fetch(CREDS, WINDOW)


async def test_the_canvas_403_message_holds_no_url_or_body(router: respx.MockRouter) -> None:
    _ = router.get(COURSES).respond(403, text="secret-detail-from-server")
    with pytest.raises(FatalError) as caught:
        await make_adapter().fetch(CREDS, WINDOW)
    assert "secret-detail" not in str(caught.value)
    assert BASE not in str(caught.value)


# ---------------------------------------------------------------- CalDAV


async def fetch_with(failure: Exception) -> Exception:
    session = FakeSession(login_error=failure)
    with pytest.raises(Exception) as caught:  # noqa: PT011  (the class is asserted by callers)
        await adapter_for(session).fetch(CALDAV_CREDS, CALDAV_WINDOW)
    return caught.value


async def test_caldav_not_found_is_fatal() -> None:
    assert isinstance(await fetch_with(NotFoundError("https://x.test/a")), FatalError)


async def test_caldav_forbidden_is_fatal() -> None:
    assert isinstance(await fetch_with(DAVError("https://x.test/a", status=403)), FatalError)


async def test_caldav_authorization_failure_stays_auth_expired() -> None:
    assert isinstance(await fetch_with(AuthorizationError("401")), AuthExpired)


async def test_a_caldav_timeout_is_transient() -> None:
    assert isinstance(await fetch_with(TimeoutError("slow")), TransientError)


async def test_a_transient_caldav_failure_logs_the_class_and_nothing_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = "https://feed.example.test/secret-path"
    with caplog.at_level(logging.WARNING):
        _ = await fetch_with(DAVError(url, reason="token fake-token"))
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "DAVError" in text
    assert url not in text
    assert "fake-token" not in text


async def test_the_caldav_fatal_message_holds_no_url() -> None:
    failure = await fetch_with(NotFoundError("https://x.test/secret-path"))
    assert "secret-path" not in str(failure)
