"""WeatherAdapter over a respx-mocked Open-Meteo, with a fake clock for the cache."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from command_center.adapters.weather import CACHE_TTL, URL, WeatherAdapter
from command_center.core.errors import FatalError, TransientError
from command_center.core.schema import event_id
from command_center.core.windows import TimeWindow
from fakes import FakeClock

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=datetime(2026, 11, 1, tzinfo=UTC), end=datetime(2026, 12, 1, tzinfo=UTC))
CREDS = {"latitude": "40.23", "longitude": "-111.66"}


def forecast(days: int = 7, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "latitude": 40.23,
        "longitude": -111.66,
        "timezone": "America/Denver",
        "utc_offset_seconds": -25200,
        "daily_units": {"time": "iso8601", "temperature_2m_max": "°F"},
        "daily": {
            "time": [f"2026-11-{7 + i:02d}" for i in range(days)],
            "temperature_2m_max": [54.4 + i for i in range(days)],
            "temperature_2m_min": [38.0 + i for i in range(days)],
            "precipitation_probability_max": [20 + i for i in range(days)],
        },
    }
    body.update(overrides)
    return body


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


async def test_each_day_becomes_a_weather_event(router: respx.MockRouter, clock: FakeClock) -> None:
    _ = router.get(URL).respond(json=forecast())

    events = await WeatherAdapter(clock).fetch(CREDS, WINDOW)

    assert len(events) == 7
    first = events[0]
    assert first.kind == "weather"
    assert first.source == "weather"
    assert first.title == "High 54°, low 38°, 20% rain"
    assert first.start == datetime(2026, 11, 7, 0, 0, tzinfo=first.start.tzinfo)  # pyright: ignore[reportOptionalMemberAccess]
    assert first.start is not None
    assert first.start.utcoffset() == timedelta(hours=-7)
    assert first.id == event_id("weather", "2026-11-07")
    assert first.urgency == 0
    assert first.fetched_at == NOW


async def test_the_request_asks_for_fahrenheit_mph_auto_timezone_and_seven_days(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(URL).respond(json=forecast())

    _ = await WeatherAdapter(clock).fetch(CREDS, WINDOW)

    params = route.calls.last.request.url.params
    assert params["latitude"] == "40.23"
    assert params["longitude"] == "-111.66"
    assert params["temperature_unit"] == "fahrenheit"
    assert params["wind_speed_unit"] == "mph"
    assert params["timezone"] == "auto"
    assert params["forecast_days"] == "7"
    assert params["daily"] == (
        "temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    )


async def test_a_second_fetch_inside_twenty_minutes_is_served_from_the_cache(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(URL).respond(json=forecast())
    adapter = WeatherAdapter(clock)

    first = await adapter.fetch(CREDS, WINDOW)
    clock.advance(CACHE_TTL - timedelta(seconds=1))
    second = await adapter.fetch(CREDS, WINDOW)

    assert route.call_count == 1
    assert second == first


async def test_the_cache_expires_after_twenty_minutes(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(URL).respond(json=forecast())
    adapter = WeatherAdapter(clock)

    _ = await adapter.fetch(CREDS, WINDOW)
    clock.advance(CACHE_TTL)
    refreshed = await adapter.fetch(CREDS, WINDOW)

    assert route.call_count == 2
    assert refreshed[0].fetched_at == NOW + CACHE_TTL


async def test_another_location_is_not_served_from_the_cache(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(URL).respond(json=forecast())
    adapter = WeatherAdapter(clock)

    _ = await adapter.fetch(CREDS, WINDOW)
    _ = await adapter.fetch({"latitude": "51.5", "longitude": "-0.12"}, WINDOW)

    assert route.call_count == 2


async def test_a_failed_request_is_not_cached(router: respx.MockRouter, clock: FakeClock) -> None:
    route = router.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=forecast())]
    )
    adapter = WeatherAdapter(clock)

    with pytest.raises(TransientError):
        _ = await adapter.fetch(CREDS, WINDOW)
    assert len(await adapter.fetch(CREDS, WINDOW)) == 7
    assert route.call_count == 2


async def test_only_days_that_start_in_the_window_are_returned(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    _ = router.get(URL).respond(json=forecast())
    window = TimeWindow(
        start=datetime(2026, 11, 9, 7, tzinfo=UTC), end=datetime(2026, 11, 11, 7, tzinfo=UTC)
    )

    events = await WeatherAdapter(clock).fetch(CREDS, window)

    assert [event.title[:7] for event in events] == ["High 56", "High 57"]


async def test_a_day_with_no_rain_figure_omits_the_rain_part(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    body = forecast(1)
    body["daily"] = {
        "time": ["2026-11-07"],
        "temperature_2m_max": [54.4],
        "temperature_2m_min": [37.6],
        "precipitation_probability_max": [None],
    }
    _ = router.get(URL).respond(json=body)

    [event] = await WeatherAdapter(clock).fetch(CREDS, WINDOW)

    assert event.title == "High 54°, low 38°"


async def test_a_day_without_temperatures_is_skipped(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    body = forecast(2)
    body["daily"] = {
        "time": ["2026-11-07", "2026-11-08"],
        "temperature_2m_max": [54.0, None],
        "temperature_2m_min": [38.0, None],
        "precipitation_probability_max": [10, None],
    }
    _ = router.get(URL).respond(json=body)

    events = await WeatherAdapter(clock).fetch(CREDS, WINDOW)

    assert [event.id for event in events] == [event_id("weather", "2026-11-07")]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, TransientError), (500, TransientError), (503, TransientError), (400, FatalError)],
)
async def test_http_errors_are_translated(
    router: respx.MockRouter, clock: FakeClock, status: int, expected: type[Exception]
) -> None:
    _ = router.get(URL).respond(status)

    with pytest.raises(expected):
        _ = await WeatherAdapter(clock).fetch(CREDS, WINDOW)


async def test_a_timeout_is_transient_and_does_not_quote_the_coordinates(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    _ = router.get(URL).mock(side_effect=httpx.ConnectTimeout("40.23,-111.66"))

    with pytest.raises(TransientError) as raised:
        _ = await WeatherAdapter(clock).fetch(CREDS, WINDOW)

    assert "40.23" not in str(raised.value)


async def test_a_malformed_body_is_fatal(router: respx.MockRouter, clock: FakeClock) -> None:
    _ = router.get(URL).respond(json={"daily": {"time": "soon"}})

    with pytest.raises(FatalError):
        _ = await WeatherAdapter(clock).fetch(CREDS, WINDOW)


@pytest.mark.parametrize(
    "creds",
    [
        {},
        {"latitude": "40.23"},
        {"latitude": "north", "longitude": "1"},
        {"latitude": "91", "longitude": "0"},
        {"latitude": "0", "longitude": "181"},
        {"latitude": "nan", "longitude": "0"},
    ],
)
async def test_bad_coordinates_are_fatal_and_make_no_request(
    router: respx.MockRouter, clock: FakeClock, creds: dict[str, str]
) -> None:
    route = router.get(URL).respond(json=forecast())

    with pytest.raises(FatalError):
        _ = await WeatherAdapter(clock).fetch(creds, WINDOW)
    assert route.call_count == 0


async def test_validate_makes_one_single_day_request(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(URL).respond(json=forecast(1))

    result = await WeatherAdapter(clock).validate(CREDS)

    assert result.ok
    assert route.calls.last.request.url.params["forecast_days"] == "1"


async def test_validate_reports_bad_coordinates_without_raising(clock: FakeClock) -> None:
    result = await WeatherAdapter(clock).validate({"latitude": "x", "longitude": "y"})

    assert not result.ok
    assert "numbers" in result.message


async def test_validate_reports_an_unreachable_service_without_raising(
    router: respx.MockRouter, clock: FakeClock
) -> None:
    _ = router.get(URL).respond(503)

    result = await WeatherAdapter(clock).validate(CREDS)

    assert not result.ok
