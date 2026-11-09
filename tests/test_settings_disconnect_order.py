"""Disconnect cancels work first, then deletes secrets, then purges; a failure says so (0085)."""

import logging
from collections.abc import AsyncIterator, Mapping

import pytest
import pytest_asyncio

from builders import NOW, make_event
from command_center.services.settings import (
    DISCONNECT_FAILED_MESSAGE,
    DISCONNECT_INCOMPLETE_MESSAGE,
    SettingsService,
)
from command_center.services.sync import SyncService
from distributed_support import TOKEN, DistributedRig, make_distributed_rig
from fake_adapter import FakeAdapter
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from generation_support import InMemoryGenerationStore
from queue_support import WINDOW
from worker_support import Backend, events, inprocess_backend

LEAK = "postgresql://cc:fake-pw@db"


class Journal:
    """Calls in the order they happened, shared by the stores a disconnect touches."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class JournalGenerations(InMemoryGenerationStore):
    def __init__(self, journal: Journal, *, fail: bool = False) -> None:
        super().__init__()
        self._journal = journal
        self.fail = fail

    def bump(self, source: str, *, user_id: str = "local") -> int:
        self._journal.calls.append("bump")
        if self.fail:
            msg = f"could not reach {LEAK}"
            raise ConnectionError(msg)
        return super().bump(source, user_id=user_id)


class JournalEvents(InMemoryEventStore):
    def __init__(self, journal: Journal, *, failures: int = 0) -> None:
        super().__init__()
        self._journal = journal
        self.failures = failures

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        self._journal.calls.append("delete_events")
        if self.failures:
            self.failures -= 1
            msg = f"could not reach {LEAK}"
            raise ConnectionError(msg)
        return super().delete_source(source, user_id=user_id)


@pytest_asyncio.fixture
async def backend() -> AsyncIterator[Backend]:
    async for item in inprocess_backend():
        yield item


async def connected_and_synced(rig: DistributedRig) -> None:
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.sync("canvas")
    await rig.worker().run_once()
    await rig.normalizer().run_once()
    assert [e.id for e in rig.events.query(WINDOW)] == ["a", "b"]


def make_rig(
    backend: Backend, journal: Journal, *, bump_fails: bool = False, purge_failures: int = 0
) -> tuple[DistributedRig, JournalGenerations, JournalEvents]:
    generations = JournalGenerations(journal, fail=bump_fails)
    event_store = JournalEvents(journal, failures=purge_failures)
    rig = make_distributed_rig(
        backend,
        FakeAdapter("canvas", script=[events("a", "b")]),
        events=event_store,
        generations=generations,
    )
    delete_secrets = rig.secrets.delete

    def journaled_delete(source: str, *, user_id: str = "local") -> None:
        journal.calls.append("delete_secrets")
        delete_secrets(source, user_id=user_id)

    rig.secrets.delete = journaled_delete  # type: ignore[method-assign]
    return rig, generations, event_store


async def test_disconnect_bumps_the_generation_then_deletes_secrets_then_purges(
    backend: Backend,
) -> None:
    journal = Journal()
    rig, _, _ = make_rig(backend, journal)
    await connected_and_synced(rig)
    journal.calls.clear()

    await rig.settings.disconnect("canvas")

    # cancel bumps first; purge bumps again before it deletes (0086)
    assert journal.calls == ["bump", "delete_secrets", "bump", "delete_events"]


async def test_a_failed_bump_aborts_before_anything_is_deleted(backend: Backend) -> None:
    journal = Journal()
    rig, generations, _ = make_rig(backend, journal)
    await connected_and_synced(rig)
    generations.fail = True
    journal.calls.clear()

    result = await rig.settings.disconnect("canvas")

    assert journal.calls == ["bump"]
    assert rig.secrets.get("canvas") == TOKEN
    assert [e.id for e in rig.events.query(WINDOW)] == ["a", "b"]
    assert rig.states.get("canvas") is not None
    assert result.sync is not None
    assert (result.sync.status, result.sync.message) == ("error", DISCONNECT_FAILED_MESSAGE)
    assert set(result.keys) == set(TOKEN)


async def test_a_failed_bump_message_and_log_hold_no_error_text(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    rig, _, _ = make_rig(backend, Journal(), bump_fails=True)

    with caplog.at_level(logging.WARNING):
        result = await rig.settings.disconnect("canvas")

    assert result.sync is not None
    assert "fake-pw" not in result.sync.message
    assert "ConnectionError" in caplog.text
    assert "fake-pw" not in caplog.text


async def test_a_failed_purge_after_the_secrets_are_gone_says_the_disconnect_is_incomplete(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    rig, generations, _ = make_rig(backend, Journal(), purge_failures=1)
    await connected_and_synced(rig)

    with caplog.at_level(logging.WARNING):
        result = await rig.settings.disconnect("canvas")

    assert rig.secrets.get("canvas") == {}
    # cancel and purge each bump, and purge bumps before its delete fails (0086)
    assert generations.current("canvas") == 2
    assert result.keys == {}
    assert result.sync is not None
    assert (result.sync.status, result.sync.message) == ("error", DISCONNECT_INCOMPLETE_MESSAGE)
    assert "fake-pw" not in result.sync.message
    assert "ConnectionError" in caplog.text
    assert "fake-pw" not in caplog.text


async def test_a_retried_disconnect_completes_after_a_failed_purge(backend: Backend) -> None:
    rig, generations, _ = make_rig(backend, Journal(), purge_failures=1)
    await connected_and_synced(rig)
    await rig.settings.disconnect("canvas")

    retry = await rig.settings.disconnect("canvas")

    assert retry.sync is None
    assert retry.keys == {}
    assert [e.id for e in rig.events.query(WINDOW)] == []
    assert rig.states.get("canvas") is None
    assert generations.current("canvas") == 4  # two disconnects, each cancel + purge bump (0086)


async def test_a_failed_purge_in_single_mode_is_also_incomplete() -> None:
    journal = Journal()
    event_store = JournalEvents(journal, failures=1)
    event_store.upsert([make_event(id="a", start=NOW)])
    adapter = FakeAdapter("canvas")
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-12345678")
    sync = SyncService({"canvas": adapter}, secrets, event_store, FakeClock(NOW))
    settings = SettingsService({"canvas": adapter}, secrets, sync)

    result = await settings.disconnect("canvas")

    assert result.sync is not None
    assert result.sync.message == DISCONNECT_INCOMPLETE_MESSAGE
    assert secrets.get("canvas") == {}


class GeminiLike:
    name = "gemini"

    async def validate(self, creds: Mapping[str, str]):  # noqa: ANN201, ARG002
        raise AssertionError


async def test_an_integration_is_deleted_without_any_cancel_or_purge(backend: Backend) -> None:
    journal = Journal()
    rig, generations, _ = make_rig(backend, journal, bump_fails=True)
    settings = SettingsService(
        {"canvas": rig.adapter},
        rig.secrets,
        rig.sync,
        {"gemini": GeminiLike()},  # type: ignore[dict-item]
    )
    rig.secrets.set("gemini", "api_key", "fake-key-12345678")

    result = await settings.disconnect("gemini")

    assert result.sync is None
    assert rig.secrets.get("gemini") == {}
    assert journal.calls == ["delete_secrets"]
    assert generations.current("gemini") == 0
