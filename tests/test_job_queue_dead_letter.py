"""JobQueue.dead_letter: give up on an in-flight job now, whatever its attempt."""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from queue_support import (
    REDIS_URL_ENV,
    Harness,
    inprocess_harness,
    make_job,
    redis_harness,
)

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
async def harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    factory = inprocess_harness if request.param == "inprocess" else redis_harness
    async for item in factory():
        yield item


async def test_a_job_on_its_first_attempt_is_dead_lettered_and_never_redelivered(
    harness: Harness,
) -> None:
    await harness.queue.publish(make_job("j1"))
    job = await harness.queue.consume("g", "c", 0)
    assert job is not None
    await harness.queue.dead_letter(job, "FatalError")

    [dead] = await harness.queue.list_dead_letters()
    assert (dead.job.id, dead.job.attempt, dead.reason) == ("j1", 1, "FatalError")
    await harness.expire_visibility()
    assert await harness.queue.consume("g", "c", 0) is None


async def test_dead_letter_of_a_job_not_in_flight_is_a_no_op(harness: Harness) -> None:
    await harness.queue.dead_letter(make_job("ghost"), "x")
    assert await harness.queue.list_dead_letters() == []


async def test_dead_letter_reasons_are_trimmed(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    job = await harness.queue.consume("g", "c", 0)
    assert job is not None
    await harness.queue.dead_letter(job, "x" * 1000)
    [dead] = await harness.queue.list_dead_letters()
    assert len(dead.reason) <= 300
