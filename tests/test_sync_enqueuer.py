"""Scheduler enqueue mode: one job per connected source, none for the rest, never a credential."""

import asyncio
from functools import partial
from typing import Any

import pytest

from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.core.jobs import Job
from command_center.core.ports import JobQueue
from command_center.services.horizon import horizon_window
from command_center.services.scheduler import SYNC_JOB_KIND, SyncEnqueuer, SyncScheduler
from fake_adapter import UnavailableSecretStore
from fakes import FakeClock, InMemorySecretStore
from queue_support import POLICY, START, VISIBILITY, SeededRng
from worker_support import SequentialIds

SOURCES = ["canvas", "gmail", "weather"]


def queues() -> dict[str, InProcessQueue]:
    clock = FakeClock(START)
    return {
        s: InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
        for s in SOURCES
    }


async def drain(queue: JobQueue) -> list[Job]:
    jobs: list[Job] = []
    while (job := await queue.consume("g", "c", 0)) is not None:
        jobs.append(job)
    return jobs


def enqueuer(secrets: InMemorySecretStore, by_source: dict[str, InProcessQueue]) -> SyncEnqueuer:
    return SyncEnqueuer(SOURCES, secrets, by_source, FakeClock(START), SequentialIds())


async def test_a_job_is_published_for_each_connected_source_only() -> None:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    secrets.set("weather", "latitude", "40.2")
    by_source = queues()

    assert await enqueuer(secrets, by_source).publish_round() == 2

    assert [len(await drain(q)) for q in by_source.values()] == [1, 0, 1]


async def test_the_job_has_the_horizon_window_ids_and_no_credential() -> None:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    by_source = queues()
    await enqueuer(secrets, by_source).publish_round()

    [job] = await drain(by_source["canvas"])
    assert (job.kind, job.source, job.attempt) == (SYNC_JOB_KIND, "canvas", 1)
    assert job.window == horizon_window(START)
    assert job.id != job.correlation_id
    assert "fake-token-1234" not in job.model_dump_json()


async def test_each_round_publishes_new_jobs_with_new_ids() -> None:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    by_source = queues()
    sync = enqueuer(secrets, by_source)
    await sync.publish_round()
    await sync.publish_round()
    first, second = await drain(by_source["canvas"])
    assert first.id != second.id


class DownQueue:
    async def publish(self, job: Job) -> None:  # noqa: ARG002
        message = "redis is down"
        raise ConnectionError(message)


async def test_one_queue_being_down_does_not_stop_the_other_sources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secrets = InMemorySecretStore()
    for source in SOURCES:
        secrets.set(source, "k", "fake-value-12345")
    by_source: dict[str, InProcessQueue] = queues()
    broken = {**by_source, "canvas": DownQueue()}
    sync = SyncEnqueuer(SOURCES, secrets, broken, FakeClock(START), SequentialIds())  # type: ignore[arg-type]

    assert await sync.publish_round() == 2

    assert len(await drain(by_source["gmail"])) == 1
    assert "ConnectionError" in caplog.text
    assert "redis is down" not in caplog.text


async def test_an_unavailable_secret_store_publishes_nothing_and_does_not_raise() -> None:
    by_source = queues()
    sync = SyncEnqueuer(
        SOURCES, UnavailableSecretStore(), by_source, FakeClock(START), SequentialIds()
    )
    assert await sync.publish_round() == 0
    assert [await drain(q) for q in by_source.values()] == [[], [], []]


async def test_the_scheduler_in_enqueue_mode_publishes_each_interval_and_syncs_nothing() -> None:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    by_source = queues()
    delays: list[float] = []
    reached = asyncio.Event()

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) == 2:
            reached.set()
            await asyncio.Event().wait()

    scheduler = SyncScheduler(None, 30, sleep=sleep, enqueue=enqueuer(secrets, by_source))
    scheduler.start()
    await asyncio.wait_for(reached.wait(), timeout=5)
    await scheduler.stop()

    assert delays == [1800, 1800]
    assert len(await drain(by_source["canvas"])) == 2


def test_the_scheduler_refuses_to_be_given_neither_a_sync_service_nor_an_enqueuer() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        SyncScheduler(None, 30)


def test_the_scheduler_refuses_to_be_given_both() -> None:
    sync_like: Any = []
    both = partial(SyncScheduler, sync_like, 30, enqueue=enqueuer(InMemorySecretStore(), queues()))
    with pytest.raises(ValueError, match="exactly one"):
        both()
