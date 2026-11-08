"""The menu-bar app reads upcoming items from its own server over loopback HTTP."""

from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
import respx

from builders import NOW, make_event
from command_center.desktop.events_client import LocalServerClient, ServerUnavailableError

BASE = "http://127.0.0.1:8765"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


def test_upcoming_asks_for_the_window_with_timezone_aware_bounds(router: respx.MockRouter) -> None:
    route = router.get("/v1/events").respond(200, json=[])
    LocalServerClient(BASE).upcoming(NOW, timedelta(days=14))
    params = route.calls.last.request.url.params
    assert params["from"] == "2026-11-07T12:00:00+00:00"
    assert params["to"] == "2026-11-21T12:00:00+00:00"


def test_upcoming_parses_events(router: respx.MockRouter) -> None:
    event = make_event(id="a", kind="assignment", due=NOW + timedelta(hours=1), status="open")
    router.get("/v1/events").respond(200, json=[event.model_dump(mode="json")])
    assert [e.id for e in LocalServerClient(BASE).upcoming(NOW, timedelta(days=1))] == ["a"]


def test_a_refused_connection_is_server_unavailable(router: respx.MockRouter) -> None:
    router.get("/v1/events").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ServerUnavailableError):
        LocalServerClient(BASE).upcoming(NOW, timedelta(days=1))


def test_a_timeout_is_server_unavailable(router: respx.MockRouter) -> None:
    router.get("/v1/events").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ServerUnavailableError):
        LocalServerClient(BASE).upcoming(NOW, timedelta(days=1))


def test_a_server_error_is_server_unavailable(router: respx.MockRouter) -> None:
    router.get("/v1/events").respond(500)
    with pytest.raises(ServerUnavailableError):
        LocalServerClient(BASE).upcoming(NOW, timedelta(days=1))


def test_an_unreadable_body_is_server_unavailable(router: respx.MockRouter) -> None:
    router.get("/v1/events").respond(200, json={"not": "a list"})
    with pytest.raises(ServerUnavailableError):
        LocalServerClient(BASE).upcoming(NOW, timedelta(days=1))


def test_healthy_reports_the_health_route(router: respx.MockRouter) -> None:
    router.get("/v1/health").respond(200, json={"status": "ok"})
    assert LocalServerClient(BASE).healthy() is True


def test_healthy_is_false_when_nothing_answers(router: respx.MockRouter) -> None:
    router.get("/v1/health").mock(side_effect=httpx.ConnectError("refused"))
    assert LocalServerClient(BASE).healthy() is False


def test_the_client_refuses_a_base_url_that_is_not_loopback() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LocalServerClient("https://mac.tail1234.ts.net")


def test_every_request_has_an_explicit_timeout(router: respx.MockRouter) -> None:
    route = router.get("/v1/events").respond(200, json=[])
    LocalServerClient(BASE).upcoming(NOW, timedelta(days=1))
    assert route.calls.last.request.extensions["timeout"]["read"] is not None
