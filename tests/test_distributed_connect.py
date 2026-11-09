"""Distributed mode through the api's services: connect enqueues, disconnect purges (0074)."""

from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
import pytest_asyncio

from command_center.core.jobs import Job, SyncReport
from command_center.core.schema import ValidationResult
from command_center.services.errors import UnknownSourceError
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_generations import create_generation_store
from command_center.storage.sqlite_states import create_sync_state_store
from distributed_support import TOKEN, DistributedRig, make_distributed_rig
from fake_adapter import FakeAdapter
from queue_support import WINDOW
from worker_support import Backend, events, inprocess_backend


@pytest_asyncio.fixture
async def backend() -> AsyncIterator[Backend]:
    async for item in inprocess_backend():
        yield item


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter("canvas", script=[events("a", "b")])


@pytest.fixture
def rig(backend: Backend, adapter: FakeAdapter, tmp_path: Path) -> DistributedRig:
    url = f"sqlite:///{tmp_path / 'shared.db'}"  # one database, as the api and normalizer share
    return make_distributed_rig(
        backend,
        adapter,
        events=create_event_store(url),
        states=create_sync_state_store(url),
        generations=create_generation_store(url),
    )


async def pending(backend: Backend) -> list[Job]:
    jobs: list[Job] = []
    while (job := await backend.queue().consume("probe", "p", 0)) is not None:
        jobs.append(job)
    return jobs


def stored(rig: DistributedRig) -> list[str]:
    return [e.id for e in rig.events.query(WINDOW)]


async def test_connect_validates_and_stores_but_runs_no_sync_in_the_api(
    rig: DistributedRig, adapter: FakeAdapter
) -> None:
    result = await rig.settings.connect("canvas", TOKEN)

    assert result.ok is True
    assert result.sync is not None
    assert result.sync.status == "syncing"
    assert len(adapter.validations) == 1
    assert adapter.fetches == []
    assert stored(rig) == []


async def test_the_route_style_follow_up_enqueues_a_job_instead_of_syncing(
    rig: DistributedRig, adapter: FakeAdapter, backend: Backend
) -> None:
    await rig.settings.connect("canvas", TOKEN)

    # api/settings.py and web/settings_routes.py run this in a background task after a connect.
    await rig.sync.sync("canvas")

    jobs = await pending(backend)
    assert [(j.source, j.kind, j.generation) for j in jobs] == [("canvas", "sync", 0)]
    assert adapter.fetches == []


async def test_a_rejected_credential_enqueues_nothing(backend: Backend) -> None:
    bad = FakeAdapter("canvas", validation=ValidationResult(ok=False, message="Bad token"))
    rig = make_distributed_rig(backend, bad)

    result = await rig.settings.connect("canvas", TOKEN)

    assert result.ok is False
    assert result.sync is None
    assert await pending(backend) == []


async def test_the_api_reads_what_the_normalizer_recorded(rig: DistributedRig) -> None:
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.sync("canvas")
    await rig.worker().run_once()
    await rig.normalizer().run_once()

    [canvas] = await rig.settings.status()

    assert canvas.sync is not None
    assert (canvas.sync.status, canvas.sync.message) == ("ok", "Synced 2 items")
    assert stored(rig) == ["a", "b"]


async def test_the_state_shown_is_redacted_and_trimmed_to_200(
    rig: DistributedRig, backend: Backend
) -> None:
    long_message = (
        "token fake-secret-abc123 for ann@example.com key fake-key-4155550123456 " + "x" * 400
    )
    report = SyncReport.model_validate(
        {
            "id": "r1",
            "correlation_id": "c1",
            "source": "canvas",
            "window": WINDOW,
            "status": "error",
            "message": long_message,
            "at": backend.clock.now(),
        }
    )
    await backend.reports().publish(report)
    await rig.normalizer().run_once()

    state = rig.sync.state("canvas")

    assert state is not None
    assert len(state.message) <= 200
    assert "ann@example.com" not in state.message
    assert "4155550123456" not in state.message
    assert "[email]" in state.message
    assert "[number]" in state.message


async def test_disconnect_purges_events_and_state_and_bumps_the_generation(
    rig: DistributedRig,
) -> None:
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.sync("canvas")
    await rig.worker().run_once()
    await rig.normalizer().run_once()
    assert stored(rig) == ["a", "b"]

    after = await rig.settings.disconnect("canvas")

    assert after.sync is None
    assert stored(rig) == []
    assert rig.states.get("canvas") is None
    assert rig.generations.current("canvas") == 2
    assert rig.secrets.get("canvas") == {}


class GeminiLike:
    name = "gemini"

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:  # noqa: ARG002
        return ValidationResult(ok=True, message="ok")


async def test_disconnecting_an_integration_does_not_touch_any_generation(
    backend: Backend, adapter: FakeAdapter
) -> None:
    rig = make_distributed_rig(backend, adapter, integrations={"gemini": GeminiLike()})

    await rig.settings.disconnect("gemini")

    assert rig.generations.current("gemini") == 0
    assert rig.generations.current("canvas") == 0


async def test_a_reconnect_after_a_disconnect_queues_a_job_with_the_new_generation(
    rig: DistributedRig, backend: Backend
) -> None:
    await rig.settings.connect("canvas", TOKEN)
    await rig.settings.disconnect("canvas")
    await rig.settings.connect("canvas", TOKEN)

    await rig.sync.sync("canvas")

    assert [j.generation for j in await pending(backend)] == [2]


async def test_post_sync_queues_the_connected_sources_and_says_they_are_syncing(
    rig: DistributedRig, backend: Backend
) -> None:
    await rig.settings.connect("canvas", TOKEN)

    states = await rig.sync.sync_all()

    assert [(s.source, s.status) for s in states] == [("canvas", "syncing")]
    assert len(await pending(backend)) == 1


async def test_post_sync_with_nothing_connected_queues_nothing(
    rig: DistributedRig, backend: Backend
) -> None:
    assert await rig.sync.sync_all() == []
    assert await pending(backend) == []


async def test_an_unknown_source_is_an_unknown_source_error(rig: DistributedRig) -> None:
    with pytest.raises(UnknownSourceError):
        await rig.sync.sync("nope")
    with pytest.raises(UnknownSourceError):
        rig.sync.mark_syncing("nope")


class DownQueue:
    """A JobQueue whose publish fails the way a lost Redis connection does."""

    async def publish(self, job: Job) -> None:  # noqa: ARG002
        msg = "redis://user:fake-pw@host down"
        raise ConnectionError(msg)


async def test_a_queue_that_is_down_is_reported_in_the_state_not_raised(
    backend: Backend, adapter: FakeAdapter
) -> None:
    rig = make_distributed_rig(backend, adapter, queue=DownQueue())  # type: ignore[arg-type]

    state = await rig.sync.sync("canvas")

    assert state.status == "error"
    assert "fake-pw" not in state.message
    assert "redis://" not in state.message
