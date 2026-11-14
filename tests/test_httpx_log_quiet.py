"""httpx and httpcore request lines never reach the log: a feed URL is a secret (0405)."""

import io
import logging
from collections.abc import Iterator

import httpx
import pytest

from command_center.adapters.json_log import configure_json_logging

FEED_URL = "https://example.invalid/fake-feed-token-123.ics"
FEED_PART = "fake-feed-token-123"
LIBRARY_LOGGERS = ("httpx", "httpcore")


@pytest.fixture
def buffer() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    saved = {name: logging.getLogger(name).level for name in LIBRARY_LOGGERS}
    stream = io.StringIO()
    configure_json_logging(stream=stream)
    yield stream
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, value in saved.items():
        logging.getLogger(name).setLevel(value)


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="BEGIN:VCALENDAR\nEND:VCALENDAR")


async def test_an_async_client_get_leaves_no_feed_url_in_the_log(buffer: io.StringIO) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ok)) as client:
        await client.get(FEED_URL)
    assert FEED_PART not in buffer.getvalue()


def test_a_sync_client_get_leaves_no_feed_url_in_the_log(buffer: io.StringIO) -> None:
    with httpx.Client(transport=httpx.MockTransport(_ok)) as client:
        client.get(FEED_URL)
    assert FEED_PART not in buffer.getvalue()


def test_the_http_loggers_are_quieter_not_off(buffer: io.StringIO) -> None:
    for name in LIBRARY_LOGGERS:
        logging.getLogger(name).warning("fixed text for %s", name)
    out = buffer.getvalue()
    assert "fixed text for httpx" in out
    assert "fixed text for httpcore" in out
