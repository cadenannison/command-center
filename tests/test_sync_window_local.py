"""The sync window is the local-day window the views use, and the roots pass the configured zone."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.app import build_container
from command_center.config import Settings
from command_center.core.windows import TimeWindow
from command_center.services.horizon import horizon_window
from command_center.services.scheduler import SyncEnqueuer
from command_center.services.sync import SyncService
from command_center.workers import __main__ as worker_main
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from queue_support import POLICY, VISIBILITY, SeededRng
from worker_support import SequentialIds

LA = ZoneInfo("America/Los_Angeles")
CREDS = {"token": "fake-canvas-token-1234"}


def secrets() -> InMemorySecretStore:
    store = InMemorySecretStore()
    for key, value in CREDS.items():
        store.set("canvas", key, value)
    return store


async def sync_window(instant: datetime, zone: ZoneInfo) -> TimeWindow:
    adapter = FakeAdapter()
    service = SyncService(
        {"canvas": adapter},
        secrets(),
        InMemoryEventStore(),
        FakeClock(instant),
        sleep=RecordingSleep(),
        zone=zone,
    )
    await service.sync("canvas")
    return adapter.fetches[0][1]


def agenda_window(instant: datetime, zone: ZoneInfo) -> TimeWindow:
    # AgendaService.attention() uses horizon_window(clock.now() in its zone)
    return horizon_window(FakeClock(instant).now().astimezone(zone))


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 11, 16, 6, 30, tzinfo=UTC),  # 22:30 on the 15th in Los Angeles
        datetime(2026, 11, 16, 7, 30, tzinfo=UTC),  # 23:30 on the 15th
        datetime(2026, 11, 16, 8, 30, tzinfo=UTC),  # 00:30 on the 16th
        datetime(2026, 3, 8, 9, 30, tzinfo=UTC),  # 01:30 on the US spring-forward day
        datetime(2026, 11, 1, 9, 30, tzinfo=UTC),  # 01:30 on the US fall-back day
        datetime(2026, 3, 9, 8, 30, tzinfo=UTC),  # 01:30 the day after the change
    ],
)
async def test_the_sync_window_equals_the_window_the_agenda_uses(instant: datetime) -> None:
    window = await sync_window(instant, LA)
    assert window == agenda_window(instant, LA)
    assert window.start.tzinfo == LA


async def test_the_window_is_not_the_utc_date_window_near_local_midnight() -> None:
    instant = datetime(2026, 11, 16, 7, 30, tzinfo=UTC)  # 23:30 on Nov 15 in Los Angeles
    window = await sync_window(instant, LA)
    utc_window = horizon_window(instant.astimezone(UTC))
    assert window != utc_window
    assert window.start == datetime(2026, 11, 1, tzinfo=LA)
    assert window.end == datetime(2027, 1, 14, tzinfo=LA)
    assert utc_window.start == datetime(2026, 11, 2, tzinfo=UTC)


async def test_the_window_over_a_dst_change_keeps_local_midnights() -> None:
    instant = datetime(2026, 3, 8, 9, 30, tzinfo=UTC)  # 01:30 PST, the hour before spring forward
    window = await sync_window(instant, LA)
    assert window.start == datetime(2026, 2, 22, tzinfo=LA)
    assert window.end == datetime(2026, 5, 7, tzinfo=LA)
    assert window.start.utcoffset() != window.end.utcoffset()  # PST at the start, PDT at the end


async def test_the_default_zone_is_utc_for_tests_and_tools() -> None:
    instant = datetime(2026, 11, 16, 7, 30, tzinfo=UTC)
    adapter = FakeAdapter()
    service = SyncService(
        {"canvas": adapter}, secrets(), InMemoryEventStore(), FakeClock(instant),
        sleep=RecordingSleep(),
    )  # fmt: skip
    await service.sync("canvas")
    assert adapter.fetches[0][1] == horizon_window(instant.astimezone(UTC))


async def test_the_enqueuer_job_window_is_the_local_day_window() -> None:
    instant = datetime(2026, 11, 16, 7, 30, tzinfo=UTC)
    clock = FakeClock(instant)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    enqueuer = SyncEnqueuer(
        ["canvas"], secrets(), {"canvas": queue}, clock, SequentialIds(), zone=LA
    )
    await enqueuer.publish_one("canvas")
    job = await queue.consume("g", "c", 0)
    assert job is not None
    assert job.window == agenda_window(instant, LA)
    assert job.window != horizon_window(instant.astimezone(UTC))


# The wiring guard: the roots pass the configured zone (not the UTC default) to the sync.


def settings_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CC_SECRET_BACKEND", "file")
    monkeypatch.setenv("CC_TZ", "America/Los_Angeles")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_single_process_root_gives_the_sync_service_the_configured_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync = build_container(settings_for(tmp_path, monkeypatch)).sync
    assert isinstance(sync, SyncService)
    assert sync._zone.key == "America/Los_Angeles"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_distributed_api_root_gives_the_enqueuer_the_configured_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(
        tmp_path, monkeypatch, CC_MODE="distributed", CC_REDIS_URL="redis://redis:6379/0"
    )
    sync = build_container(settings).sync
    enqueuer = sync._enqueuer  # type: ignore[attr-defined]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert isinstance(enqueuer, SyncEnqueuer)
    assert enqueuer._zone.key == "America/Los_Angeles"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


async def test_the_scheduler_worker_root_gives_the_enqueuer_the_configured_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(
        tmp_path, monkeypatch, CC_MODE="distributed", CC_REDIS_URL="redis://redis:6379/0"
    )
    seen: list[SyncEnqueuer] = []

    class StopScheduler:
        def __init__(self, _sync: object, _interval: int, *, enqueue: SyncEnqueuer) -> None:
            seen.append(enqueue)

        async def run(self) -> None:
            return None

    class FakeQueue:
        @classmethod
        def from_url(cls, *_args: object, **_kwargs: object) -> "FakeQueue":
            return cls()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(worker_main, "SyncScheduler", StopScheduler)
    monkeypatch.setattr(worker_main, "RedisStreamsQueue", FakeQueue)
    await worker_main._run_scheduler(settings)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert seen[0]._zone.key == "America/Los_Angeles"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
