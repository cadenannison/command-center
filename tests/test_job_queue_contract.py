"""One contract suite for every JobQueue. Redis cases run only when CC_TEST_REDIS_URL is set."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio

from command_center.core.jobs import VISIBILITY_TIMEOUT_REASON, Job
from command_center.core.redact import trim
from queue_support import (
    POLICY,
    REDIS_URL_ENV,
    Harness,
    inprocess_harness,
    make_job,
    redis_harness,
)

GROUP = "workers"
CONSUMER = "worker-1"
LONG_AFTER_CAP = timedelta(minutes=5)

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


async def take(harness: Harness, consumer: str = CONSUMER) -> Job | None:
    return await harness.queue.consume(GROUP, consumer, 0)


async def test_consume_on_an_empty_queue_returns_none(harness: Harness) -> None:
    assert await take(harness) is None


async def test_jobs_of_one_source_are_delivered_in_publish_order(harness: Harness) -> None:
    order = [("a1", "canvas"), ("b1", "gmail"), ("a2", "canvas"), ("b2", "gmail"), ("a3", "canvas")]
    for job_id, source in order:
        await harness.queue.publish(make_job(job_id, source))
    delivered: list[Job] = []
    while (job := await take(harness)) is not None:
        delivered.append(job)
        await harness.queue.ack(job)
    assert [j.id for j in delivered if j.source == "canvas"] == ["a1", "a2", "a3"]
    assert [j.id for j in delivered if j.source == "gmail"] == ["b1", "b2"]


async def test_a_delivered_job_is_the_published_job(harness: Harness) -> None:
    job = make_job("j1")
    await harness.queue.publish(job)
    assert await take(harness) == job


async def test_an_acked_job_is_not_delivered_again(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    job = await take(harness)
    assert job is not None
    await harness.queue.ack(job)
    await harness.expire_visibility()
    assert await take(harness) is None
    assert await harness.queue.list_dead_letters() == []


async def test_an_unacked_job_is_not_redelivered_before_the_visibility_timeout(
    harness: Harness,
) -> None:
    await harness.queue.publish(make_job("j1"))
    assert await take(harness) is not None
    assert await take(harness, "worker-2") is None


async def test_an_unacked_job_is_redelivered_after_the_visibility_timeout(
    harness: Harness,
) -> None:
    await harness.queue.publish(make_job("j1"))
    first = await take(harness)
    await harness.expire_visibility()
    second = await take(harness, "worker-2")
    assert first is not None
    assert second is not None
    assert (second.id, second.attempt) == (first.id, first.attempt + 1)
    assert second.correlation_id == first.correlation_id


async def test_a_failed_job_is_retried_only_after_its_delay(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    first = await take(harness)
    assert first is not None
    await harness.queue.fail(first, "timeout")
    assert await take(harness) is None
    await harness.advance(LONG_AFTER_CAP)
    retry = await take(harness)
    assert retry is not None
    assert (retry.id, retry.attempt, retry.correlation_id) == ("j1", 2, first.correlation_id)


async def test_a_job_is_dead_lettered_after_max_attempts(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    for expected_attempt in range(1, POLICY.max_attempts + 1):
        job = await take(harness)
        assert job is not None
        assert job.attempt == expected_attempt
        await harness.queue.fail(job, "still broken")
        await harness.advance(LONG_AFTER_CAP)
    assert await take(harness) is None
    [dead] = await harness.queue.list_dead_letters()
    assert dead.job.id == "j1"
    assert dead.job.attempt == POLICY.max_attempts
    assert dead.job.correlation_id == "corr-j1"
    assert dead.reason == "still broken"


async def test_a_long_failure_reason_is_trimmed_in_the_dead_letter(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    for _ in range(POLICY.max_attempts):
        job = await take(harness)
        assert job is not None
        await harness.queue.fail(job, "x" * 5000)
        await harness.advance(LONG_AFTER_CAP)
    [dead] = await harness.queue.list_dead_letters()
    assert dead.reason == trim("x" * 5000, 300)


async def test_a_job_that_keeps_timing_out_is_dead_lettered(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    for _ in range(POLICY.max_attempts):
        assert await take(harness) is not None
        await harness.expire_visibility()
    assert await take(harness) is None
    [dead] = await harness.queue.list_dead_letters()
    assert dead.job.id == "j1"


async def test_a_late_ack_from_a_superseded_delivery_completes_the_job(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    original = await take(harness)
    await harness.expire_visibility()
    duplicate = await take(harness, "worker-2")
    assert original is not None
    assert duplicate is not None
    await harness.queue.ack(original)
    await harness.queue.ack(duplicate)
    await harness.expire_visibility()
    assert await take(harness) is None
    assert await harness.queue.list_dead_letters() == []


async def test_acking_twice_changes_nothing(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    await harness.queue.publish(make_job("j2"))
    first = await take(harness)
    assert first is not None
    await harness.queue.ack(first)
    await harness.queue.ack(first)
    second = await take(harness)
    assert second is not None
    assert second.id == "j2"


async def test_failing_an_acked_job_does_not_bring_it_back(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    job = await take(harness)
    assert job is not None
    await harness.queue.ack(job)
    await harness.queue.fail(job, "late failure")
    await harness.advance(LONG_AFTER_CAP)
    assert await take(harness) is None
    assert await harness.queue.list_dead_letters() == []


async def test_a_blocked_consumer_receives_a_job_published_meanwhile(harness: Harness) -> None:
    waiting = asyncio.create_task(harness.queue.consume(GROUP, CONSUMER, 3000))
    await harness.settle()
    await harness.queue.publish(make_job("j1"))
    job = await asyncio.wait_for(waiting, timeout=5)
    assert job is not None
    assert job.id == "j1"


async def test_a_retried_job_that_times_out_keeps_counting_attempts(harness: Harness) -> None:
    await harness.queue.publish(make_job("j1"))
    first = await take(harness)
    assert first is not None
    await harness.queue.fail(first, "timeout")
    await harness.advance(LONG_AFTER_CAP)
    second = await take(harness)
    assert second is not None
    assert second.attempt == 2
    await harness.expire_visibility()
    third = await take(harness, "worker-2")
    assert third is not None
    assert third.attempt == 3
    await harness.expire_visibility()
    assert await take(harness) is None
    [dead] = await harness.queue.list_dead_letters()
    assert (dead.job.id, dead.job.attempt) == ("j1", 3)
    assert dead.reason == VISIBILITY_TIMEOUT_REASON


async def test_a_fail_from_a_superseded_delivery_acts_on_the_live_delivery(
    harness: Harness,
) -> None:
    await harness.queue.publish(make_job("j1"))
    original = await take(harness)
    await harness.expire_visibility()
    live = await take(harness, "worker-2")
    assert original is not None
    assert live is not None
    await harness.queue.fail(original, "slow worker gave up")
    await harness.advance(LONG_AFTER_CAP)
    retry = await take(harness)
    assert retry is not None
    assert retry.attempt == live.attempt + 1
