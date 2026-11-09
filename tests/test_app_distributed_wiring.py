"""The api's composition root in both modes: where sync state lives, who runs syncs (0074)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.adapters.queue_redis import RedisStreamsQueue
from command_center.api import create_app as create_api_app
from command_center.app import build_container
from command_center.config import Settings
from command_center.core.jobs import Job
from command_center.core.sync_state import SyncState
from command_center.services.queued_sync import QueuedSyncService
from command_center.services.sync import SyncService
from command_center.storage.sqlite_states import create_sync_state_store

FAKE_REDIS = "redis://:fake-hunter2pw@127.0.0.1:1/0"  # nothing listens: the tests never connect


def make_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, distributed: bool
) -> Settings:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'wiring.db'}")
    monkeypatch.setenv("CC_TZ", "America/Denver")
    if distributed:
        monkeypatch.setenv("CC_MODE", "distributed")
        monkeypatch.setenv("CC_REDIS_URL", FAKE_REDIS)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_single_mode_syncs_in_process_and_has_nothing_to_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container = build_container(make_settings(monkeypatch, tmp_path, distributed=False))

    assert isinstance(container.sync, SyncService)
    assert container.close is None


def test_single_mode_writes_each_state_to_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = make_settings(monkeypatch, tmp_path, distributed=False)
    app = create_api_app(lambda: build_container(settings))

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/v1/sync")

    stored = create_sync_state_store(settings.database_url).get("canvas")
    assert stored is not None
    assert stored.status == "reconnect"


def test_distributed_mode_queues_syncs_and_closes_its_queues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container = build_container(make_settings(monkeypatch, tmp_path, distributed=True))

    assert isinstance(container.sync, QueuedSyncService)
    assert container.close is not None


def test_the_distributed_api_shows_the_state_the_normalizer_wrote_to_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = make_settings(monkeypatch, tmp_path, distributed=True)
    normalizer_side = create_sync_state_store(settings.database_url)  # another process's handle
    normalizer_side.put(
        SyncState(
            source="canvas",
            status="ok",
            message="Synced 4 items",
            at=datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
        )
    )
    app = create_api_app(lambda: build_container(settings))

    with TestClient(app, base_url="http://localhost") as client:
        shown = {row["source"]: row["sync"] for row in client.get("/v1/settings").json()}

    assert shown["canvas"] == {
        "source": "canvas",
        "status": "ok",
        "message": "Synced 4 items",
        "at": "2026-11-07T12:00:00Z",
    }
    assert shown["gmail"] is None


def test_a_manual_sync_with_nothing_connected_returns_no_states_and_queues_no_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    published = record_published_jobs(monkeypatch)
    settings = make_settings(monkeypatch, tmp_path, distributed=True)
    app = create_api_app(lambda: build_container(settings))

    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/v1/sync").json() == []

    assert published == []


def test_the_distributed_api_runs_no_sync_and_a_manual_sync_queues_only_connected_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    published = record_published_jobs(monkeypatch)
    settings = make_settings(monkeypatch, tmp_path, distributed=True)
    KeyringSecretStore().set("canvas", "token", "fake-token-12345678")
    app = create_api_app(lambda: build_container(settings))

    with TestClient(app, base_url="http://localhost") as client:
        shown = [(row["source"], row["status"]) for row in client.post("/v1/sync").json()]

    # "syncing" and not "ok", "reconnect" or "error": the api fetched nothing, it queued a job.
    assert shown == [("canvas", "syncing")]
    assert published == ["canvas"]


def record_published_jobs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the Redis publish, so the test sees which sources got a job and Redis is unused."""
    published: list[str] = []

    async def publish(_queue: RedisStreamsQueue, job: Job) -> None:
        published.append(job.source)

    monkeypatch.setattr(RedisStreamsQueue, "publish", publish)
    return published
