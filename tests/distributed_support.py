"""A distributed deployment in one process: the api's services, a sync worker and a normalizer.

They share a queue, a report stream and the three stores, as the real roles share Redis and the
database. `backend` picks in-process or Redis for the queue and the report stream.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from command_center.core.ports import (
    EventStore,
    GenerationStore,
    IntegrationAdapter,
    JobQueue,
    SyncStateStore,
)
from command_center.services.queued_sync import QueuedSyncService
from command_center.services.scheduler import SyncEnqueuer
from command_center.services.settings import SettingsService
from command_center.workers.normalizer import Normalizer
from command_center.workers.sync_worker import SyncWorker
from fake_adapter import FakeAdapter
from fakes import InMemoryEventStore, InMemorySecretStore
from generation_support import InMemoryGenerationStore
from worker_support import (
    Backend,
    ClockSleep,
    InMemorySyncStateStore,
    SequentialIds,
    make_worker,
)

TOKEN = {"token": "fake-token-12345678"}


@dataclass
class DistributedRig:
    backend: Backend
    adapter: FakeAdapter
    secrets: InMemorySecretStore
    events: EventStore
    states: SyncStateStore
    generations: GenerationStore
    sync: QueuedSyncService
    settings: SettingsService

    def worker(self, consumer: str = "canvas-1") -> SyncWorker:
        """A sync worker: a second `queue()` models a second process (see Backend)."""
        return make_worker(
            self.adapter,
            self.backend.queue(),
            self.backend.reports(),
            self.backend.clock,
            secrets=self.secrets,
            consumer=consumer,
        )

    def normalizer(self, consumer: str = "norm-1") -> Normalizer:
        return Normalizer(
            self.backend.reports(),
            self.events,
            self.states,
            generations=self.generations,
            consumer=consumer,
            block_ms=0,
            sleep=ClockSleep(self.backend.clock),
        )


def make_distributed_rig(  # noqa: PLR0913
    backend: Backend,
    adapter: FakeAdapter,
    *,
    events: EventStore | None = None,
    states: SyncStateStore | None = None,
    generations: GenerationStore | None = None,
    queue: JobQueue | None = None,
    integrations: Mapping[str, IntegrationAdapter] | None = None,
) -> DistributedRig:
    secrets = InMemorySecretStore()
    event_store = events or InMemoryEventStore()
    state_store = states or InMemorySyncStateStore()
    generation_store = generations or InMemoryGenerationStore()
    enqueuer = SyncEnqueuer(
        [adapter.name],
        secrets,
        {adapter.name: queue or backend.queue()},
        backend.clock,
        SequentialIds(),
        generations=generation_store,
    )
    sync = QueuedSyncService(
        [adapter.name], enqueuer, state_store, event_store, generation_store, backend.clock
    )
    settings = SettingsService({adapter.name: adapter}, secrets, sync, integrations)
    return DistributedRig(
        backend, adapter, secrets, event_store, state_store, generation_store, sync, settings
    )
