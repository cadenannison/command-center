"""IcalFeedAdapter: feeds mocked with respx, DNS stubbed, SSRF cases and all-or-nothing fetches."""

import socket
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from builders import NOW
from command_center.adapters.ical_feed import MAX_FEED_BYTES, IcalFeedAdapter
from command_center.core.errors import AuthExpired, FatalError, TransientError
from ics_support import DENVER, WINDOW, load

FEED_1 = "https://feeds.example.com/course-1/token-abc123"
FEED_2 = "https://feeds.example.com/course-2/token-def456"
SECRET_PARTS = ("token-abc123", "token-def456", "feeds.example.com")


class FakeClock:
    def now(self):  # noqa: ANN201
        return NOW


def resolves_to(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    info = (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))

    def fake(*_args: object, **_kwargs: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [info]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def sent(route: respx.Route, index: int) -> httpx.Request:
    return route.calls[index].request  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    resolves_to(monkeypatch, "93.184.216.34")


@pytest.fixture
def adapter() -> IcalFeedAdapter:
    return IcalFeedAdapter(DENVER, FakeClock())


def creds(*urls: str) -> dict[str, str]:
    return {"urls": "\n".join(urls)}


def ics(body: str, **headers: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers=headers)


@respx.mock
async def test_fetch_combines_every_feed_as_events(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(ics(load("allday.ics")))
    respx.get(FEED_2).mock(ics(load("floating.ics")))
    events = await adapter.fetch(creds(FEED_1, FEED_2), WINDOW)
    assert {e.title for e in events} == {
        "Veterans Day break",
        "Retreat",
        "Clocks go back",
        "Floating morning",
        "Floating late",
    }
    assert {e.kind for e in events} == {"event"}
    assert {e.source for e in events} == {"learningsuite"}


@respx.mock
async def test_fetch_expands_recurrence_across_dst_in_a_feed(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(ics(load("recurring.ics")))
    events = await adapter.fetch(creds(FEED_1), WINDOW)
    assert len(events) == 4


@respx.mock
async def test_blank_lines_and_padding_in_urls_are_ignored(adapter: IcalFeedAdapter) -> None:
    route = respx.get(FEED_1).mock(ics(load("floating.ics")))
    await adapter.fetch({"urls": f"\n  {FEED_1}  \n\n"}, WINDOW)
    assert route.call_count == 1


@respx.mock
async def test_same_uid_in_two_feeds_gives_distinct_events(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(ics(load("floating.ics")))
    respx.get(FEED_2).mock(ics(load("floating.ics")))
    events = await adapter.fetch(creds(FEED_1, FEED_2), WINDOW)
    assert len(events) == len({e.id for e in events}) == 4


@respx.mock
async def test_event_raw_names_the_feed_number_but_not_the_url(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(ics(load("floating.ics")))
    events = await adapter.fetch(creds(FEED_1), WINDOW)
    assert all(e.raw["feed"] == 1 for e in events)
    assert not any(part in str(e.raw) for e in events for part in SECRET_PARTS)


@respx.mock
async def test_one_failing_feed_raises_instead_of_returning_the_rest(
    adapter: IcalFeedAdapter,
) -> None:
    respx.get(FEED_1).mock(ics(load("floating.ics")))
    respx.get(FEED_2).mock(httpx.Response(500))
    with pytest.raises(TransientError, match="Feed 2"):
        await adapter.fetch(creds(FEED_1, FEED_2), WINDOW)


@respx.mock
async def test_a_failing_first_feed_stops_before_the_second_is_requested(
    adapter: IcalFeedAdapter,
) -> None:
    respx.get(FEED_1).mock(httpx.Response(500))
    second = respx.get(FEED_2).mock(ics(load("floating.ics")))
    with pytest.raises(TransientError, match="Feed 1"):
        await adapter.fetch(creds(FEED_1, FEED_2), WINDOW)
    assert not second.called


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(401), AuthExpired),
        (httpx.Response(403), AuthExpired),
        (httpx.Response(404), FatalError),
        (httpx.Response(410), FatalError),
        (httpx.Response(429), TransientError),
        (httpx.Response(503), TransientError),
        (httpx.Response(200, text="<html>login</html>"), FatalError),
        (httpx.Response(304), FatalError),
    ],
)
@respx.mock
async def test_failure_class_follows_the_response(
    adapter: IcalFeedAdapter, response: httpx.Response, error: type[Exception]
) -> None:
    respx.get(FEED_1).mock(response)
    with pytest.raises(error, match="Feed 1") as caught:
        await adapter.fetch(creds(FEED_1), WINDOW)
    assert not any(part in str(caught.value) for part in SECRET_PARTS)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
@respx.mock
async def test_network_failures_are_transient_and_quote_nothing(
    adapter: IcalFeedAdapter, failure: Exception
) -> None:
    respx.get(FEED_1).mock(side_effect=failure)
    with pytest.raises(TransientError, match="Feed 1") as caught:
        await adapter.fetch(creds(FEED_1), WINDOW)
    assert not any(part in str(caught.value) for part in SECRET_PARTS)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/feed.ics",
        "https://127.0.0.1/feed.ics",
        "https://10.1.2.3/feed.ics",
        "https://192.168.0.5/feed.ics",
        "https://169.254.169.254/latest",
        "https://[::1]/feed.ics",
        "http://feeds.example.com/feed.ics",
        "https://user:pw@feeds.example.com/feed.ics",
        "file:///etc/passwd",
    ],
)
@respx.mock
async def test_unsafe_urls_are_rejected_before_any_request(
    adapter: IcalFeedAdapter, url: str
) -> None:
    route = respx.route().mock(ics(load("floating.ics")))
    with pytest.raises(FatalError, match="Feed 1: the URL is not a public https address"):
        await adapter.fetch(creds(url), WINDOW)
    assert not route.called


@respx.mock
async def test_public_name_resolving_to_a_private_address_is_rejected(
    adapter: IcalFeedAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolves_to(monkeypatch, "10.0.0.7")
    route = respx.route().mock(ics(load("floating.ics")))
    with pytest.raises(FatalError, match="Feed 1: the host is not a public address"):
        await adapter.fetch(creds(FEED_1), WINDOW)
    assert not route.called


@respx.mock
async def test_lookup_timeout_propagates_as_transient_naming_the_feed(
    adapter: IcalFeedAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(_host: str) -> None:
        msg = "host lookup timed out"
        raise TransientError(msg)

    monkeypatch.setattr("command_center.adapters.ical_feed.ensure_public_host", slow)
    with pytest.raises(TransientError, match="Feed 1: host lookup timed out"):
        await adapter.fetch(creds(FEED_1), WINDOW)


@respx.mock
async def test_redirects_are_not_followed(adapter: IcalFeedAdapter) -> None:
    target = respx.get("https://elsewhere.example.com/x").mock(ics(load("floating.ics")))
    respx.get(FEED_1).mock(
        httpx.Response(302, headers={"location": "https://elsewhere.example.com/x"})
    )
    with pytest.raises(FatalError, match="Feed 1: the URL redirects"):
        await adapter.fetch(creds(FEED_1), WINDOW)
    assert not target.called


@respx.mock
async def test_redirect_to_an_internal_address_is_never_requested(adapter: IcalFeedAdapter) -> None:
    internal = respx.get("https://10.0.0.1/admin").mock(ics("secret"))
    respx.get(FEED_1).mock(httpx.Response(301, headers={"location": "https://10.0.0.1/admin"}))
    with pytest.raises(FatalError):
        await adapter.fetch(creds(FEED_1), WINDOW)
    assert not internal.called


@respx.mock
async def test_body_over_the_cap_is_rejected_while_streaming(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(httpx.Response(200, content=b"x" * (MAX_FEED_BYTES + 1)))
    with pytest.raises(FatalError, match="Feed 1: larger than 5 MB"):
        await adapter.fetch(creds(FEED_1), WINDOW)


async def chunks(count: int, size: int) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield b"x" * size


@respx.mock
async def test_a_chunked_body_over_the_cap_is_cut_off_without_a_declared_length(
    adapter: IcalFeedAdapter,
) -> None:
    respx.get(FEED_1).mock(httpx.Response(200, content=chunks(6, MAX_FEED_BYTES // 5)))
    with pytest.raises(FatalError, match="Feed 1: larger than 5 MB"):
        await adapter.fetch(creds(FEED_1), WINDOW)


@respx.mock
async def test_an_overall_timeout_is_transient(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(side_effect=TimeoutError())
    with pytest.raises(TransientError, match="Feed 1: timed out"):
        await adapter.fetch(creds(FEED_1), WINDOW)


@respx.mock
async def test_a_rule_that_cannot_be_expanded_fails_the_fetch_naming_the_feed(
    adapter: IcalFeedAdapter,
) -> None:
    bad = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:a\nDTSTAMP:20261001T000000Z\n"
        "DTSTART:20261110T090000\nRRULE:FREQ=NOPE\nSUMMARY:Bad\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    respx.get(FEED_1).mock(ics(bad))
    with pytest.raises(FatalError, match="Feed 1: a recurring item could not be expanded"):
        await adapter.fetch(creds(FEED_1), WINDOW)


@respx.mock
async def test_declared_length_over_the_cap_is_rejected(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(
        httpx.Response(200, headers={"content-length": str(MAX_FEED_BYTES + 1)}, content=b"")
    )
    with pytest.raises(FatalError, match="larger than 5 MB"):
        await adapter.fetch(creds(FEED_1), WINDOW)


@respx.mock
async def test_requests_carry_a_timeout_and_no_redirect_following(adapter: IcalFeedAdapter) -> None:
    route = respx.get(FEED_1).mock(ics(load("floating.ics")))
    await adapter.fetch(creds(FEED_1), WINDOW)
    assert sent(route, -1).extensions["timeout"] == {
        "connect": 10.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }


@respx.mock
async def test_an_etag_is_sent_back_and_a_304_reuses_the_cached_body(
    adapter: IcalFeedAdapter,
) -> None:
    route = respx.get(FEED_1).mock(
        side_effect=[ics(load("floating.ics"), etag='"v1"'), httpx.Response(304)]
    )
    first = await adapter.fetch(creds(FEED_1), WINDOW)
    second = await adapter.fetch(creds(FEED_1), WINDOW)
    assert sent(route, 0).headers.get("if-none-match") is None
    assert sent(route, 1).headers["if-none-match"] == '"v1"'
    assert [e.id for e in second] == [e.id for e in first]


@respx.mock
async def test_a_changed_body_replaces_the_cached_one(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(
        side_effect=[
            ics(load("floating.ics"), etag='"v1"'),
            ics(load("allday.ics"), etag='"v2"'),
        ]
    )
    await adapter.fetch(creds(FEED_1), WINDOW)
    second = await adapter.fetch(creds(FEED_1), WINDOW)
    assert "Retreat" in {e.title for e in second}


@respx.mock
async def test_a_response_without_an_etag_drops_the_cache_entry(adapter: IcalFeedAdapter) -> None:
    route = respx.get(FEED_1).mock(
        side_effect=[
            ics(load("floating.ics"), etag='"v1"'),
            ics(load("floating.ics")),
            ics(load("floating.ics")),
        ]
    )
    for _ in range(3):
        await adapter.fetch(creds(FEED_1), WINDOW)
    assert sent(route, 2).headers.get("if-none-match") is None


@respx.mock
async def test_a_dropped_feed_loses_its_cached_etag(adapter: IcalFeedAdapter) -> None:
    first = respx.get(FEED_1).mock(ics(load("floating.ics"), etag='"v1"'))
    respx.get(FEED_2).mock(ics(load("floating.ics"), etag='"v2"'))
    await adapter.fetch(creds(FEED_1, FEED_2), WINDOW)
    await adapter.fetch(creds(FEED_2), WINDOW)
    await adapter.fetch(creds(FEED_1), WINDOW)
    assert sent(first, 1).headers.get("if-none-match") is None


async def test_fetch_without_urls_is_fatal_not_an_empty_result(adapter: IcalFeedAdapter) -> None:
    with pytest.raises(FatalError, match="no feed URLs"):
        await adapter.fetch({}, WINDOW)


def test_the_source_name_is_learningsuite(adapter: IcalFeedAdapter) -> None:
    assert adapter.name == "learningsuite"


@respx.mock
async def test_validate_accepts_working_feeds(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(ics(load("floating.ics")))
    respx.get(FEED_2).mock(ics(load("allday.ics")))
    result = await adapter.validate(creds(FEED_1, FEED_2))
    assert (result.ok, result.message) == (True, "Connected 2 feeds")


@pytest.mark.parametrize(
    "response",
    [httpx.Response(403), httpx.Response(404), httpx.Response(200, text="not a calendar")],
)
@respx.mock
async def test_validate_names_the_failing_feed_number_never_the_url(
    adapter: IcalFeedAdapter, response: httpx.Response
) -> None:
    respx.get(FEED_1).mock(ics(load("floating.ics")))
    respx.get(FEED_2).mock(response)
    result = await adapter.validate(creds(FEED_1, FEED_2))
    assert result.ok is False
    assert "Feed 2" in result.message
    assert not any(part in result.message for part in SECRET_PARTS)


@respx.mock
async def test_validate_rejects_an_unsafe_url_by_number(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(ics(load("floating.ics")))
    result = await adapter.validate(creds(FEED_1, "https://10.0.0.1/feed.ics"))
    assert (result.ok, "Feed 2" in result.message, "10.0.0.1" in result.message) == (
        False,
        True,
        False,
    )


@respx.mock
async def test_validate_lets_a_transient_failure_propagate(adapter: IcalFeedAdapter) -> None:
    respx.get(FEED_1).mock(httpx.Response(502))
    with pytest.raises(TransientError, match="Feed 1"):
        await adapter.validate(creds(FEED_1))


async def test_validate_asks_for_a_url_when_there_is_none(adapter: IcalFeedAdapter) -> None:
    result = await adapter.validate({"urls": "  \n "})
    assert result.ok is False
