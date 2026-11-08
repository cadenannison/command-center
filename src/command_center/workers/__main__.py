"""Composition root for distributed mode: one process per role (decision 0070).

    python -m command_center.workers --source canvas   consume sync jobs for one source
    python -m command_center.workers --normalizer      apply the fetched events to the stores
    python -m command_center.workers --scheduler       publish one sync job per connected source

Every role needs CC_REDIS_URL; credentials come from the secret store (CC_SECRET_BACKEND), never
from a job. The classes that do the work live beside this file and know nothing of Redis.
"""

import argparse
import asyncio
import contextlib
import signal
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from command_center.adapters.json_log import configure_json_logging
from command_center.adapters.queue_redis import (
    RedisReportStream,
    RedisStreamsQueue,
    source_queue_prefix,
)
from command_center.adapters.secret_backend import build_secret_store
from command_center.adapters.source_registry import build_source_adapters
from command_center.adapters.system_clock import SystemClock
from command_center.adapters.system_ids import UuidIdSource
from command_center.adapters.system_rng import SystemRng
from command_center.config import Settings
from command_center.core.resilience import DEFAULT_RETRY_POLICY, CircuitBreaker
from command_center.services.scheduler import SyncEnqueuer, SyncScheduler
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_generations import create_generation_store
from command_center.storage.sqlite_sink import create_report_sink
from command_center.storage.sqlite_states import create_sync_state_store
from command_center.workers.normalizer import Normalizer
from command_center.workers.sync_worker import SyncWorker

REPORTS_PREFIX = "cc-reports"
BREAKER_FAILURES = 5
BREAKER_COOL_DOWN = timedelta(minutes=5)
HEARTBEAT_SECONDS = 15.0


def source_prefix(source: str) -> str:
    """The Redis key prefix of one source's job queue: one queue per source (decision 0070)."""
    return source_queue_prefix(source)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Read the role from the command line; exactly one of the three is required."""
    parser = argparse.ArgumentParser(prog="python -m command_center.workers")
    role = parser.add_mutually_exclusive_group(required=True)
    role.add_argument("--source", help="consume sync jobs for this source, e.g. canvas")
    role.add_argument("--normalizer", action="store_true", help="apply reports to the stores")
    role.add_argument("--scheduler", action="store_true", help="enqueue a sync per source")
    parser.add_argument("--heartbeat-file", type=Path, help="touched every 15 s for healthchecks")
    return parser.parse_args(argv)


async def _heartbeat(path: Path) -> None:
    while True:
        await asyncio.to_thread(path.touch)
        await asyncio.sleep(HEARTBEAT_SECONDS)


def _redis_url(settings: Settings) -> str:
    if not settings.redis_url:
        sys.exit("CC_REDIS_URL is not set: every worker role talks to Redis")
    return settings.redis_url


async def _run_worker(settings: Settings, source: str) -> None:
    clock, ids = SystemClock(), UuidIdSource()
    adapters = build_source_adapters(ZoneInfo(settings.tz), clock)
    if source not in adapters:
        sys.exit(f"Unknown source {source!r}; choose one of {', '.join(adapters)}")
    url = _redis_url(settings)
    queue = RedisStreamsQueue.from_url(
        url, clock, SystemRng(), prefix=source_prefix(source), policy=DEFAULT_RETRY_POLICY
    )
    reports = RedisReportStream.from_url(url, clock, prefix=REPORTS_PREFIX)
    worker = SyncWorker(
        adapters[source],
        build_secret_store(settings.secret_backend, settings.data_dir),
        queue,
        reports,
        CircuitBreaker(BREAKER_FAILURES, BREAKER_COOL_DOWN, clock),
        clock,
        ids,
        DEFAULT_RETRY_POLICY,
        consumer=f"{source}-{ids.new_id()[:8]}",
    )
    try:
        await worker.run()
    finally:
        await queue.aclose()
        await reports.aclose()


async def _run_normalizer(settings: Settings) -> None:
    clock, ids = SystemClock(), UuidIdSource()
    reports = RedisReportStream.from_url(_redis_url(settings), clock, prefix=REPORTS_PREFIX)
    generations = create_generation_store(settings.database_url)
    sink = create_report_sink(settings.database_url)
    events = create_event_store(settings.database_url)
    states = create_sync_state_store(settings.database_url)
    normalizer = Normalizer(
        reports,
        events,
        states,
        generations=generations,
        sink=sink,
        consumer=f"normalizer-{ids.new_id()[:8]}",
    )
    try:
        await normalizer.run()
    finally:
        await reports.aclose()
        generations.close()
        sink.close()
        events.close()
        states.close()


async def _run_scheduler(settings: Settings) -> None:
    clock = SystemClock()
    sources = list(build_source_adapters(ZoneInfo(settings.tz), clock))
    url = _redis_url(settings)
    queues = {
        source: RedisStreamsQueue.from_url(
            url, clock, SystemRng(), prefix=source_prefix(source), policy=DEFAULT_RETRY_POLICY
        )
        for source in sources
    }
    generations = create_generation_store(settings.database_url)
    enqueuer = SyncEnqueuer(
        sources,
        build_secret_store(settings.secret_backend, settings.data_dir),
        queues,
        clock,
        UuidIdSource(),
        generations=generations,
    )
    scheduler = SyncScheduler(None, settings.sync_interval_minutes, enqueue=enqueuer)
    try:
        await scheduler.run()
    finally:
        for queue in queues.values():
            await queue.aclose()
        generations.close()


async def _serve(args: argparse.Namespace, settings: Settings) -> None:
    main_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, main_task.cancel if main_task else lambda: None)
    with contextlib.suppress(asyncio.CancelledError):
        async with asyncio.TaskGroup() as group:
            if args.heartbeat_file is not None:
                group.create_task(_heartbeat(args.heartbeat_file))
            if args.normalizer:
                group.create_task(_run_normalizer(settings))
            elif args.scheduler:
                group.create_task(_run_scheduler(settings))
            else:
                group.create_task(_run_worker(settings, args.source))


def main(argv: Sequence[str] | None = None) -> None:  # pragma: no cover - process entry point
    """Run one worker role until stopped."""
    args = parse_args(argv)
    configure_json_logging()
    asyncio.run(_serve(args, Settings()))


if __name__ == "__main__":  # pragma: no cover
    main()
