"""Every adapter body goes through one capped reader (audit card 04, decision 0409)."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from command_center.adapters.canvas_client import MAX_PAGE_BYTES, CanvasClient
from command_center.adapters.http_cap import ReplyTooLarge, read_capped
from command_center.adapters.ical_feed import MAX_FEED_BYTES, read_feed_capped
from command_center.adapters.weather import MAX_FORECAST_BYTES, WeatherAdapter
from command_center.core.errors import FatalError
from command_center.core.windows import TimeWindow
from fakes import FakeClock

ORIGIN = "https://canvas.example.edu"
WINDOW = TimeWindow(start=datetime(2026, 11, 1, tzinfo=UTC), end=datetime(2026, 12, 1, tzinfo=UTC))
CREDS = {"latitude": "40.23", "longitude": "-111.66"}


async def no_sleep(_seconds: float) -> None:
    return None


def padded(payload: object, size: int) -> bytes:
    raw = json.dumps(payload).encode()
    return raw + b" " * (size - len(raw))


def canvas_with(handler: httpx.MockTransport) -> CanvasClient:
    return CanvasClient(httpx.AsyncClient(transport=handler), ORIGIN, no_sleep)


def weather_with(body: bytes, headers: dict[str, str] | None = None) -> WeatherAdapter:
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers=headers)

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return WeatherAdapter(FakeClock(datetime(2026, 11, 7, 12, 0, tzinfo=UTC)), client=client)


FORECAST = {
    "latitude": 40.23,
    "longitude": -111.66,
    "timezone": "America/Denver",
    "utc_offset_seconds": -25200,
    "daily": {
        "time": ["2026-11-07"],
        "temperature_2m_max": [54.4],
        "temperature_2m_min": [38.0],
        "precipitation_probability_max": [20],
    },
}


# ---------------------------------------------------------------- Canvas


async def test_a_canvas_page_one_byte_over_the_cap_is_fatal() -> None:
    body = padded([], MAX_PAGE_BYTES + 1)
    client = canvas_with(httpx.MockTransport(lambda _r: httpx.Response(200, content=body)))
    with pytest.raises(FatalError, match="larger than 2 MB"):
        await client.pages("/api/v1/courses")


async def test_a_canvas_page_exactly_at_the_cap_parses() -> None:
    body = padded([{"id": 1}], MAX_PAGE_BYTES)
    client = canvas_with(httpx.MockTransport(lambda _r: httpx.Response(200, content=body)))
    assert await client.pages("/api/v1/courses") == [{"id": 1}]


async def test_a_canvas_declared_length_over_the_cap_is_refused() -> None:
    headers = {"content-length": str(MAX_PAGE_BYTES + 1)}
    client = canvas_with(
        httpx.MockTransport(lambda _r: httpx.Response(200, headers=headers, content=b"[]"))
    )
    with pytest.raises(FatalError, match="larger than 2 MB"):
        await client.pages("/api/v1/courses")


# ---------------------------------------------------------------- forecast


async def test_a_forecast_one_byte_over_the_cap_is_fatal() -> None:
    adapter = weather_with(padded(FORECAST, MAX_FORECAST_BYTES + 1))
    with pytest.raises(FatalError, match="larger than 1 MB"):
        await adapter.fetch(CREDS, WINDOW)


async def test_a_forecast_exactly_at_the_cap_parses() -> None:
    adapter = weather_with(padded(FORECAST, MAX_FORECAST_BYTES))
    assert len(await adapter.fetch(CREDS, WINDOW)) == 1


async def test_a_forecast_declared_length_over_the_cap_is_refused() -> None:
    adapter = weather_with(b"{}", {"content-length": str(MAX_FORECAST_BYTES + 1)})
    with pytest.raises(FatalError, match="larger than 1 MB"):
        await adapter.fetch(CREDS, WINDOW)


# ---------------------------------------------------------------- feed


async def stream_response(
    chunks: list[bytes], headers: dict[str, str] | None = None
) -> tuple[httpx.Response, list[int]]:
    """A streamed response whose body is `chunks`; the list records the bytes pulled so far."""
    pulled: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        for chunk in chunks:
            pulled.append(len(chunk))
            yield chunk

    request = httpx.Request("GET", "https://example.test/")
    return httpx.Response(200, headers=headers, content=body(), request=request), pulled


async def test_a_feed_one_byte_over_the_cap_is_fatal() -> None:
    response, _ = await stream_response([b"x" * (MAX_FEED_BYTES + 1)])
    with pytest.raises(FatalError, match="Feed 1: larger than 5 MB"):
        await read_feed_capped(1, response)


async def test_a_feed_exactly_at_the_cap_is_returned() -> None:
    response, _ = await stream_response([b"x" * MAX_FEED_BYTES])
    assert len(await read_feed_capped(1, response)) == MAX_FEED_BYTES


async def test_a_feed_declared_length_over_the_cap_is_refused_before_any_read() -> None:
    response, pulled = await stream_response([b"x"], {"content-length": str(MAX_FEED_BYTES + 1)})
    with pytest.raises(FatalError):
        await read_feed_capped(1, response)
    assert pulled == []


# ---------------------------------------------------------------- the shared reader


async def test_the_reader_checks_before_extending_so_the_buffer_stays_at_the_cap() -> None:
    chunks = [b"a" * 400] * 10
    response, pulled = await stream_response(chunks)
    with pytest.raises(ReplyTooLarge):
        await read_capped(response, limit=1000)
    # The third chunk would make 1200: it is read (one chunk of overshoot) but never added.
    assert len(pulled) == 3
    assert sum(pulled[:-1]) <= 1000


async def test_the_reader_returns_a_body_exactly_at_the_limit() -> None:
    response, _ = await stream_response([b"a" * 500, b"b" * 500])
    assert len(await read_capped(response, limit=1000)) == 1000


async def test_the_reader_refuses_a_declared_length_over_the_limit_unread() -> None:
    response, pulled = await stream_response([b"x"], {"content-length": "1001"})
    with pytest.raises(ReplyTooLarge):
        await read_capped(response, limit=1000)
    assert pulled == []
