"""A job and its report carry the source's generation; the worker copies it across (0074)."""

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.adapters.inprocess_reports import InProcessReportStream
from command_center.core.jobs import Job, SyncReport
from command_center.services.scheduler import SyncEnqueuer
from fake_adapter import UnavailableSecretStore
from fakes import FakeClock, InMemorySecretStore
from generation_support import InMemoryGenerationStore
from queue_support import POLICY, START, VISIBILITY, SeededRng, make_job
from worker_support import (
    SequentialIds,
    adapter_with,
    events,
    make_report,
    make_worker,
)


def test_a_job_and_a_report_default_to_generation_zero() -> None:
    assert make_job("j1").generation == 0
    assert make_report().generation == 0


def test_a_generation_survives_the_json_round_trip_the_queues_use() -> None:
    job = make_job("j1").model_copy(update={"generation": 3})
    assert Job.model_validate_json(job.model_dump_json()).generation == 3
    report = make_report().model_copy(update={"generation": 4})
    assert SyncReport.model_validate_json(report.model_dump_json()).generation == 4


def test_a_job_written_before_generations_existed_still_parses() -> None:
    # A job already in Redis when the api is upgraded has no "generation" key.
    old = make_job("j1").model_dump_json(exclude={"generation"})
    assert Job.model_validate_json(old).generation == 0


@pytest.mark.parametrize("model", [Job, SyncReport])
def test_a_negative_generation_is_refused(model: type[Job | SyncReport]) -> None:
    base = (make_job("j1") if model is Job else make_report()).model_dump(mode="json")
    with pytest.raises(ValidationError):
        model.model_validate({**base, "generation": -1})


async def test_the_worker_stamps_the_jobs_generation_on_every_kind_of_report() -> None:
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    reports = InProcessReportStream(clock, visibility_timeout=VISIBILITY)
    worker = make_worker(adapter_with(events("a")), queue, reports, clock)
    await queue.publish(make_job("j1").model_copy(update={"generation": 5}))

    assert await worker.run_once() is True

    report = await reports.consume("g", "c", 0)
    assert report is not None
    assert (report.status, report.generation) == ("ok", 5)


async def test_a_reconnect_report_carries_the_generation_too() -> None:
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    reports = InProcessReportStream(clock, visibility_timeout=VISIBILITY)
    worker = make_worker(
        adapter_with(events("a")), queue, reports, clock, secrets=InMemorySecretStore()
    )
    await queue.publish(make_job("j1").model_copy(update={"generation": 2}))

    await worker.run_once()

    report = await reports.consume("g", "c", 0)
    assert report is not None
    assert (report.status, report.generation) == ("reconnect", 2)


async def test_the_enqueuer_stamps_the_generation_current_when_it_publishes() -> None:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    generations = InMemoryGenerationStore()
    generations.bump("canvas")
    generations.bump("canvas")
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    enqueuer = SyncEnqueuer(
        ["canvas"], secrets, {"canvas": queue}, clock, SequentialIds(), generations=generations
    )

    await enqueuer.publish_round()

    job = await queue.consume("g", "c", 0)
    assert job is not None
    assert job.generation == 2


async def test_the_enqueuer_publishes_one_source_without_asking_the_secret_store() -> None:
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    enqueuer = SyncEnqueuer(
        ["canvas"], UnavailableSecretStore(), {"canvas": queue}, clock, SequentialIds()
    )

    await enqueuer.publish_one("canvas")

    assert (await queue.consume("g", "c", 0)) is not None


async def test_publish_connected_names_the_sources_it_queued() -> None:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    clock = FakeClock(START)
    queues = {
        s: InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
        for s in ("canvas", "gmail")
    }
    enqueuer = SyncEnqueuer(["canvas", "gmail"], secrets, queues, clock, SequentialIds())

    assert await enqueuer.publish_connected() == ["canvas"]


class DisconnectsWhileReadingCredentials(InMemorySecretStore):
    """The user disconnects between the scheduler's credentials read and its next step."""

    def __init__(self, generations: InMemoryGenerationStore) -> None:
        super().__init__()
        self._generations = generations

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:
        found = super().get(source, user_id=user_id)
        self._generations.bump(source)
        return found


async def test_a_disconnect_during_the_credentials_read_keeps_the_old_generation() -> None:
    generations = InMemoryGenerationStore()
    secrets = DisconnectsWhileReadingCredentials(generations)
    secrets.set("canvas", "token", "fake-token-1234")
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    enqueuer = SyncEnqueuer(
        ["canvas"], secrets, {"canvas": queue}, clock, SequentialIds(), generations=generations
    )

    await enqueuer.publish_connected()

    job = await queue.consume("g", "c", 0)
    assert job is not None
    assert job.generation == 0  # the normalizer drops it: the source is now at generation 1
