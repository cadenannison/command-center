"""A database error while reading a sync state is "unknown", as in single mode (decision 0084)."""

import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from command_center.core.sync_state import SyncState
from distributed_support import make_distributed_rig
from fake_adapter import FakeAdapter
from worker_support import Backend, InMemorySyncStateStore, inprocess_backend

DATABASE_URL = "postgres://user:fake-pw-9f3a@db.internal/cc"


class UnreadableStateStore(InMemorySyncStateStore):
    """A state store whose database cannot be read; the error text carries a connection URL."""

    def get(self, source: str, *, user_id: str = "local") -> SyncState | None:  # noqa: ARG002
        msg = f"could not connect to {DATABASE_URL}"
        raise ConnectionError(msg)


@pytest_asyncio.fixture
async def backend() -> AsyncIterator[Backend]:
    async for item in inprocess_backend():
        yield item


async def test_a_state_store_that_cannot_be_read_gives_an_unknown_state_not_an_error(
    backend: Backend,
) -> None:
    rig = make_distributed_rig(backend, FakeAdapter("canvas"), states=UnreadableStateStore())

    assert rig.sync.state("canvas") is None


async def test_the_settings_status_still_lists_the_source_when_its_state_cannot_be_read(
    backend: Backend,
) -> None:
    rig = make_distributed_rig(backend, FakeAdapter("canvas"), states=UnreadableStateStore())

    [status] = await rig.settings.status()

    assert (status.source, status.sync) == ("canvas", None)


async def test_the_failed_read_is_logged_by_class_without_the_connection_url(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    rig = make_distributed_rig(backend, FakeAdapter("canvas"), states=UnreadableStateStore())

    with caplog.at_level(logging.WARNING):
        _ = rig.sync.state("canvas")

    assert "ConnectionError" in caplog.text
    assert "fake-pw-9f3a" not in caplog.text
    assert "db.internal" not in caplog.text
