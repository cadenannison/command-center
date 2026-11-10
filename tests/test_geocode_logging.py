"""The city search text stays out of uvicorn's access log and of the app's own log lines."""

import logging
from collections.abc import Iterator

import pytest

from command_center.adapters.log_redaction import (
    ACCESS_LOGGER,
    QueryStringFilter,
    install_query_redaction,
)
from geocode_support import TYPED_QUERY, make_geocode_rig

ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


def access_record(path: str) -> logging.LogRecord:
    """A record shaped like the one uvicorn's access logger makes."""
    return logging.LogRecord(
        ACCESS_LOGGER,
        logging.INFO,
        __file__,
        1,
        ACCESS_FORMAT,
        ("127.0.0.1:50000", "GET", path, "1.1", 200),
        None,
    )


@pytest.fixture
def access_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger(ACCESS_LOGGER)
    before = list(logger.filters)
    yield logger
    logger.filters[:] = before


def test_the_filter_cuts_the_query_off_a_geocode_path() -> None:
    record = access_record(f"/v1/geocode?q={TYPED_QUERY}")

    assert QueryStringFilter().filter(record) is True

    assert record.getMessage() == '127.0.0.1:50000 - "GET /v1/geocode HTTP/1.1" 200'


def test_the_filter_leaves_other_paths_alone() -> None:
    path = "/v1/agenda/day?date=2026-11-09"
    record = access_record(path)

    _ = QueryStringFilter().filter(record)

    assert path in record.getMessage()


def test_the_filter_ignores_a_record_that_is_not_shaped_like_an_access_line() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "plain %s", ("text",), None)

    assert QueryStringFilter().filter(record) is True
    assert record.getMessage() == "plain text"


def test_installing_twice_attaches_one_filter(access_logger: logging.Logger) -> None:
    install_query_redaction()
    install_query_redaction()

    assert sum(isinstance(item, QueryStringFilter) for item in access_logger.filters) == 1


def test_an_installed_filter_cleans_the_line_a_handler_receives(
    access_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    install_query_redaction()
    caplog.set_level(logging.INFO, logger=ACCESS_LOGGER)

    access_logger.info(
        ACCESS_FORMAT, "127.0.0.1:1", "GET", f"/v1/geocode?q={TYPED_QUERY}", "1.1", 200
    )

    assert caplog.records
    assert TYPED_QUERY not in caplog.text


def test_a_search_that_succeeds_and_one_that_fails_log_no_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    ok = make_geocode_rig()
    _ = ok.client.get("/v1/geocode", params={"q": TYPED_QUERY})
    refused = make_geocode_rig(wired=False)
    _ = refused.client.get("/v1/geocode", params={"q": TYPED_QUERY})
    short = make_geocode_rig()
    _ = short.client.get("/v1/geocode", params={"q": "x"})

    # the test client's own httpx logs the URL it requests; the app under test is what counts
    app_lines = [r.getMessage() for r in caplog.records if not r.name.startswith("httpx")]
    assert app_lines
    assert all(TYPED_QUERY not in line for line in app_lines)
