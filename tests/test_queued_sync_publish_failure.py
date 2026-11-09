"""A publish that fails is an error state for that source, not a silent omission (decision 0085)."""

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.adapters.queue_redis import RedisStreamsQueue
from command_center.api import create_app as create_api_app
from command_center.app import build_container
from command_center.config import Settings
from command_center.core.jobs import Job
from command_center.core.sync_state import SyncState
from command_center.services.queued_sync import QUEUE_FAILED_MESSAGE, QueuedSyncService
from command_center.services.scheduler import SyncEnqueuer
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from generation_support import InMemoryGenerationStore
from queue_support import POLICY, START, VISIBILITY, SeededRng
from worker_support import InMemorySyncStateStore, SequentialIds

SOURCES = ["canvas", "gmail", "weather"]
FAKE_REDIS = "redis://:fake-hunter2pw@127.0.0.1:1/0"  # nothing listens: every publish is refused


class DownQueue:
    """A JobQueue whose publish fails the way a lost Redis connection does."""

    async def publish(self, job: Job) -> None:  # noqa: ARG002
        msg = "redis://user:fake-pw@host down"
        raise ConnectionError(msg)


class UnreadableStates(InMemorySyncStateStore):
    """A state store whose reads fail the way a lost database connection does."""

    def get(self, source: str, *, user_id: str = "local") -> SyncState | None:  # noqa: ARG002
        msg = "postgresql://cc:fake-pw@db down"
        raise ConnectionError(msg)


def make_service(
    down: set[str], connected: list[str], states: InMemorySyncStateStore | None = None
) -> tuple[QueuedSyncService, dict[str, InProcessQueue]]:
    clock = FakeClock(START)
    healthy = {
        s: InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
        for s in SOURCES
    }
    queues: dict[str, Any] = {s: DownQueue() if s in down else healthy[s] for s in SOURCES}
    secrets = InMemorySecretStore()
    for source in connected:
        secrets.set(source, "token", "fake-token-1234")
    enqueuer = SyncEnqueuer(
        SOURCES, secrets, queues, clock, SequentialIds(), generations=InMemoryGenerationStore()
    )
    service = QueuedSyncService(
        SOURCES,
        enqueuer,
        states or InMemorySyncStateStore(),
        InMemoryEventStore(),
        InMemoryGenerationStore(),
        clock,
    )
    return service, healthy


async def queued(queue: InProcessQueue) -> int:
    count = 0
    while await queue.consume("probe", "p", 0) is not None:
        count += 1
    return count


async def test_sync_all_reports_an_error_state_for_a_source_whose_queue_is_down() -> None:
    service, _ = make_service(down={"gmail"}, connected=["canvas", "gmail"])

    states = {s.source: s for s in await service.sync_all()}

    assert states["gmail"].status == "error"
    assert states["gmail"].message == QUEUE_FAILED_MESSAGE
    assert "fake-pw" not in states["gmail"].message
    assert "redis://" not in states["gmail"].message


async def test_one_source_failing_does_not_stop_the_others_from_being_queued() -> None:
    service, healthy = make_service(down={"canvas"}, connected=SOURCES)

    states = {s.source: s.status for s in await service.sync_all()}

    assert states == {"canvas": "error", "gmail": "syncing", "weather": "syncing"}
    assert [await queued(healthy[s]) for s in ("gmail", "weather")] == [1, 1]


async def test_every_connected_source_is_an_error_when_every_queue_is_down() -> None:
    service, _ = make_service(down=set(SOURCES), connected=["canvas", "weather"])

    states = {s.source: s.status for s in await service.sync_all()}

    assert states == {"canvas": "error", "weather": "error"}


async def test_an_unreadable_state_of_a_source_not_queued_does_not_fail_the_round() -> None:
    service, healthy = make_service(down=set(), connected=["canvas"], states=UnreadableStates())

    states = await service.sync_all()

    assert [(s.source, s.status) for s in states] == [("canvas", "syncing")]
    assert await queued(healthy["canvas"]) == 1


class UnreadableGenerations(InMemoryGenerationStore):
    def current(self, source: str, *, user_id: str = "local") -> int:  # noqa: ARG002
        msg = "postgresql://cc:fake-pw@db down"
        raise ConnectionError(msg)


async def test_an_unreadable_generation_fails_only_the_connected_sources() -> None:
    clock = FakeClock(START)
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-1234")
    queues = {
        s: InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
        for s in SOURCES
    }
    enqueuer = SyncEnqueuer(
        SOURCES, secrets, queues, clock, SequentialIds(), generations=UnreadableGenerations()
    )
    service = QueuedSyncService(
        SOURCES,
        enqueuer,
        InMemorySyncStateStore(),
        InMemoryEventStore(),
        InMemoryGenerationStore(),
        clock,
    )

    states = await service.sync_all()

    assert [(s.source, s.status) for s in states] == [("canvas", "error")]


async def test_a_source_that_is_not_connected_is_not_an_error_when_the_queues_are_down() -> None:
    service, _ = make_service(down=set(SOURCES), connected=[])

    assert await service.sync_all() == []


async def test_a_failed_publish_is_logged_by_class_only(caplog: pytest.LogCaptureFixture) -> None:
    service, _ = make_service(down={"gmail"}, connected=["gmail"])

    with caplog.at_level(logging.WARNING):
        await service.sync_all()

    assert "ConnectionError" in caplog.text
    assert "fake-pw" not in caplog.text


def test_post_sync_with_redis_down_returns_an_error_state_per_connected_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'down.db'}")
    monkeypatch.setenv("CC_TZ", "America/Denver")
    monkeypatch.setenv("CC_MODE", "distributed")
    monkeypatch.setenv("CC_REDIS_URL", FAKE_REDIS)

    async def refuse(_queue: RedisStreamsQueue, job: Job) -> None:  # noqa: ARG001
        msg = f"connection refused by {FAKE_REDIS}"
        raise ConnectionError(msg)

    monkeypatch.setattr(RedisStreamsQueue, "publish", refuse)  # no socket is opened
    KeyringSecretStore().set("canvas", "token", "fake-token-1234")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    app = create_api_app(lambda: build_container(settings))

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/v1/sync")

    assert response.status_code == 200
    [row] = response.json()
    assert (row["source"], row["status"], row["message"]) == (
        "canvas",
        "error",
        QUEUE_FAILED_MESSAGE,
    )
    assert "fake-hunter2pw" not in response.text
