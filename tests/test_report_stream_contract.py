"""One contract suite for every ReportStream. Redis cases run only when CC_TEST_REDIS_URL is set."""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from queue_support import REDIS_URL_ENV
from worker_support import Backend, events, inprocess_backend, make_report, redis_backend

GROUP = "normalizers"

BACKENDS = [
    pytest.param("inprocess", id="inprocess"),
    pytest.param(
        "redis",
        id="redis",
        marks=pytest.mark.skipif(
            not os.environ.get(REDIS_URL_ENV), reason=f"{REDIS_URL_ENV} is not set"
        ),
    ),
]


@pytest_asyncio.fixture(params=BACKENDS)
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[Backend]:
    factory = inprocess_backend if request.param == "inprocess" else redis_backend
    async for item in factory():
        yield item


async def test_a_consumed_report_is_the_published_report_with_its_events(backend: Backend) -> None:
    reports = backend.reports()
    report = make_report(items=events("a", "b"))
    await reports.publish(report)
    assert await reports.consume(GROUP, "c1", 0) == report


async def test_reports_are_delivered_in_publish_order(backend: Backend) -> None:
    reports = backend.reports()
    for name in ("r1", "r2", "r3"):
        await reports.publish(make_report(name))
    delivered: list[str] = []
    while (report := await reports.consume(GROUP, "c1", 0)) is not None:
        delivered.append(report.id)
        await reports.ack(report)
    assert delivered == ["r1", "r2", "r3"]


async def test_an_empty_stream_returns_none(backend: Backend) -> None:
    assert await backend.reports().consume(GROUP, "c1", 0) is None


async def test_an_acked_report_is_not_delivered_again(backend: Backend) -> None:
    reports = backend.reports()
    await reports.publish(make_report())
    report = await reports.consume(GROUP, "c1", 0)
    assert report is not None
    await reports.ack(report)
    await backend.expire()
    assert await reports.consume(GROUP, "c1", 0) is None


async def test_an_unacked_report_is_delivered_again_after_the_visibility_timeout(
    backend: Backend,
) -> None:
    reports = backend.reports()
    await reports.publish(make_report())
    assert await reports.consume(GROUP, "c1", 0) is not None
    assert await reports.consume(GROUP, "c2", 0) is None
    await backend.expire()
    again = await backend.reports().consume(GROUP, "c2", 0)
    assert again is not None
    assert again.id == "r1"


async def test_a_report_never_acked_is_dead_lettered_after_the_delivery_cap(
    backend: Backend,
) -> None:
    reports = backend.reports()
    await reports.publish(make_report(items=events("a")))
    for _ in range(3):  # the cap in worker_support
        assert await backend.reports().consume(GROUP, "c", 0) is not None
        await backend.expire()
    assert await backend.reports().consume(GROUP, "c", 0) is None

    [dead] = await reports.list_dead_reports()
    assert (dead.id, dead.source, dead.correlation_id) == ("r1", "canvas", "corr-r1")
    assert not hasattr(dead, "events")


async def test_dead_letter_gives_up_on_an_in_flight_report_at_once(backend: Backend) -> None:
    reports = backend.reports()
    await reports.publish(make_report())
    report = await reports.consume(GROUP, "c1", 0)
    assert report is not None
    await reports.dead_letter(report, "ValueError")
    await backend.expire()
    assert await reports.consume(GROUP, "c1", 0) is None
    assert [d.reason for d in await reports.list_dead_reports()] == ["ValueError"]


async def test_ack_and_dead_letter_of_a_report_not_in_flight_do_nothing(backend: Backend) -> None:
    reports = backend.reports()
    report = make_report()
    await reports.ack(report)
    await reports.dead_letter(report, "x")
    assert await reports.list_dead_reports() == []
