"""GeocodeService: the rate limit, the redacted failures and the cap, on a fake clock."""

import logging
from datetime import timedelta

import pytest

from command_center.core.errors import FatalError, TransientError
from command_center.core.geocode import MAX_CANDIDATES
from command_center.services.errors import GeocodeRateLimitedError, GeocodeUnavailableError
from command_center.services.geocode import SEARCH_LIMIT, SEARCH_WINDOW, GeocodeService
from fakes import FakeClock
from geocode_support import NOW, TYPED_QUERY, FakeGeocoder, place


def make(outcome: object = None) -> tuple[GeocodeService, FakeGeocoder, FakeClock]:
    geocoder = FakeGeocoder(outcome)  # pyright: ignore[reportArgumentType]
    clock = FakeClock(NOW)
    return GeocodeService(geocoder, clock), geocoder, clock


async def test_a_search_returns_what_the_geocoder_found() -> None:
    service, _, _ = make([place("Provo"), place("Provo", "Quebec")])

    found = await service.search("Provo")

    assert [(item.name, item.region) for item in found] == [("Provo", "Utah"), ("Provo", "Quebec")]


async def test_the_query_is_trimmed_and_its_whitespace_collapsed_before_it_is_sent() -> None:
    service, geocoder, _ = make()

    _ = await service.search("  Salt   Lake \t City ")

    assert geocoder.queries == ["Salt Lake City"]


async def test_a_query_too_short_to_search_returns_nothing_and_asks_nobody() -> None:
    service, geocoder, _ = make()

    assert await service.search("  a ") == []
    assert geocoder.queries == []


async def test_a_geocoder_that_returns_too_many_is_cut_to_five() -> None:
    service, _, _ = make([place(f"Town {i}") for i in range(9)])

    assert len(await service.search("Town")) == MAX_CANDIDATES


async def test_the_eleventh_search_in_a_minute_is_refused_before_it_reaches_the_geocoder() -> None:
    service, geocoder, _ = make()
    for _ in range(SEARCH_LIMIT):
        _ = await service.search("Provo")

    with pytest.raises(GeocodeRateLimitedError) as caught:
        _ = await service.search("Provo")

    assert len(geocoder.queries) == SEARCH_LIMIT
    assert caught.value.retry_after_seconds == int(SEARCH_WINDOW.total_seconds())


async def test_the_wait_shrinks_as_the_clock_moves_and_rounds_up() -> None:
    service, _, clock = make()
    for _ in range(SEARCH_LIMIT):
        _ = await service.search("Provo")
    clock.advance(timedelta(seconds=20, milliseconds=500))

    with pytest.raises(GeocodeRateLimitedError) as caught:
        _ = await service.search("Provo")

    assert caught.value.retry_after_seconds == 40


async def test_a_search_is_allowed_again_when_the_oldest_has_left_the_window() -> None:
    service, geocoder, clock = make()
    for _ in range(SEARCH_LIMIT):
        _ = await service.search("Provo")
    clock.advance(SEARCH_WINDOW)

    _ = await service.search("Provo")

    assert len(geocoder.queries) == SEARCH_LIMIT + 1


async def test_a_refused_search_does_not_extend_the_wait() -> None:
    service, _, clock = make()
    for _ in range(SEARCH_LIMIT):
        _ = await service.search("Provo")
    clock.advance(timedelta(seconds=30))
    for _ in range(5):
        with pytest.raises(GeocodeRateLimitedError):
            _ = await service.search("Provo")
    clock.advance(timedelta(seconds=30))

    assert await service.search("Provo")


async def test_a_failed_search_still_uses_up_the_budget() -> None:
    service, geocoder, _ = make(TransientError("Open-Meteo city search is unreachable"))
    for _ in range(SEARCH_LIMIT):
        with pytest.raises(GeocodeUnavailableError):
            _ = await service.search("Provo")

    with pytest.raises(GeocodeRateLimitedError):
        _ = await service.search("Provo")

    assert len(geocoder.queries) == SEARCH_LIMIT


@pytest.mark.parametrize("error", [TransientError, FatalError])
async def test_a_provider_failure_is_one_redacted_message(error: type[Exception]) -> None:
    text = "Open-Meteo said ada@example.com account 12345678 refused"
    service, _, _ = make(error(text))

    with pytest.raises(GeocodeUnavailableError) as caught:
        _ = await service.search("Provo")

    message = str(caught.value)
    assert message.startswith("City search failed: Open-Meteo said")
    assert "ada@example.com" not in message
    assert "12345678" not in message
    assert caught.value.__cause__ is None


async def test_a_long_provider_message_is_cut_to_200_characters() -> None:
    service, _, _ = make(FatalError("x" * 500))

    with pytest.raises(GeocodeUnavailableError) as caught:
        _ = await service.search("Provo")

    assert len(str(caught.value)) <= 200


async def test_a_bug_in_the_geocoder_is_not_swallowed() -> None:
    service, _, _ = make(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        _ = await service.search("Provo")


async def test_nothing_the_service_logs_carries_the_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _, _ = make(TransientError(f"unreachable for {TYPED_QUERY}"))
    caplog.set_level(logging.DEBUG)
    for _ in range(SEARCH_LIMIT):
        with pytest.raises(GeocodeUnavailableError):
            _ = await service.search(TYPED_QUERY)
    with pytest.raises(GeocodeRateLimitedError):
        _ = await service.search(TYPED_QUERY)

    assert caplog.records
    assert TYPED_QUERY not in caplog.text
