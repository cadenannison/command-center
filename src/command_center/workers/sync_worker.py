"""Consumes sync jobs for one source and publishes what the adapter fetched (decision 0070).

Transient failure: the queue retries it with backoff (`RetryPolicy` lives in the queue) and the
per-source circuit breaker counts it. Fatal: dead-letter at once. AuthExpired, or no credentials:
report `reconnect` and ack, never retry. Log lines carry the exception class, never its message.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

from command_center.core.errors import AuthExpired, FatalError, SecretStoreError, TransientError
from command_center.core.jobs import Job, SyncReport
from command_center.core.ports import (
    Clock,
    IdSource,
    JobQueue,
    ReportStream,
    SecretStore,
    SourceAdapter,
)
from command_center.core.resilience import BreakerPhase, CircuitBreaker, RetryPolicy
from command_center.core.schema import Event
from command_center.services.errors import error_text, safe_message
from command_center.services.scheduler import SYNC_JOB_KIND

logger = logging.getLogger(__name__)

NOT_CONNECTED = "Not connected: no credentials stored"
RECONNECT = "Credentials were rejected; reconnect"
type Sleep = Callable[[float], Awaitable[None]]


class SyncWorker:
    """One worker for one source: consume a job, fetch, report, ack."""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        adapter: SourceAdapter,
        secrets: SecretStore,
        queue: JobQueue,
        reports: ReportStream,
        breaker: CircuitBreaker,
        clock: Clock,
        ids: IdSource,
        policy: RetryPolicy,
        *,
        consumer: str,
        group: str = "sync-workers",
        block_ms: int = 1000,
        poll_seconds: float = 1.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._adapter = adapter
        self._source = adapter.name
        self._secrets = secrets
        self._queue = queue
        self._reports = reports
        self._breaker = breaker
        self._breaker_state = breaker.initial()
        self._clock = clock
        self._ids = ids
        self._policy = policy
        self._consumer = consumer
        self._group = group
        self._block_ms = block_ms
        self._poll_seconds = poll_seconds
        self._sleep = sleep

    async def run(self) -> None:
        """Handle jobs until cancelled; an error in one pass is logged and the loop goes on."""
        while True:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001  (Redis errors are not builtins; class logged)
                logger.warning(
                    "worker pass for %s failed: %s",
                    self._source,
                    type(exc).__name__,
                    extra={"source": self._source, "error_class": type(exc).__name__},
                )
                await self._sleep(self._poll_seconds)

    async def run_once(self) -> bool:
        """Take and handle at most one job; True if there was one.

        While the breaker is open nothing is consumed: the jobs wait in the queue untouched
        instead of burning their attempts against a source known to be down.
        """
        if not self._breaker.allow(self._breaker_state):
            await self._sleep(self._poll_seconds)
            return False
        job = await self._queue.consume(self._group, self._consumer, self._block_ms)
        if job is None:
            return False
        await self._handle(job)
        return True

    async def _handle(self, job: Job) -> None:
        if job.source != self._source or job.kind != SYNC_JOB_KIND:
            logger.error(
                "job is not a sync of %s",
                self._source,
                extra={"source": self._source, "job_id": job.id, "error_class": "WrongJob"},
            )
            await self._queue.dead_letter(job, "WrongJob")
            return
        await self._sync(job)

    async def _sync(self, job: Job) -> None:
        try:
            creds = await asyncio.to_thread(self._secrets.get, self._source)
        except SecretStoreError as exc:
            await self._retry(job, exc, source_failed=False)
            return
        if not creds:
            await self._report(job, "reconnect", NOT_CONNECTED)
            await self._queue.ack(job)
            return
        try:
            events = await self._adapter.fetch(creds, job.window)
        except AuthExpired:
            self._note_success()  # the source answered, so a half-open trial is over
            await self._report(job, "reconnect", RECONNECT)
            await self._queue.ack(job)
        except TransientError as exc:
            self._note_failure()
            await self._retry(job, exc, source_failed=True)
        except FatalError as exc:
            await self._give_up(job, exc)
        except Exception as exc:  # noqa: BLE001  (an adapter bug or leaked vendor error: not the source's fault)
            await self._retry(job, exc, source_failed=False)
        else:
            self._note_success()
            await self._report(job, "ok", "", events)
            await self._queue.ack(job)

    async def _retry(self, job: Job, exc: Exception, *, source_failed: bool) -> None:
        error_class = type(exc).__name__
        extra = {"source": self._source, "job_id": job.id, "attempt": job.attempt}
        extra |= {"correlation_id": job.correlation_id, "error_class": error_class}
        if self._policy.exhausted(job.attempt):
            logger.error("sync of %s gave up: %s", self._source, error_class, extra=extra)
            if source_failed:
                message = f"Source unreachable after {job.attempt} attempts: {error_text(exc)}"
            else:
                message = f"Sync failed after {job.attempt} attempts: {error_class}"
            await self._report(job, "error", message)
        else:
            logger.warning("sync of %s will retry: %s", self._source, error_class, extra=extra)
        await self._queue.fail(job, error_class)

    async def _give_up(self, job: Job, exc: FatalError) -> None:
        self._note_success()
        error_class = type(exc).__name__
        logger.error(
            "sync of %s dead-lettered: %s",
            self._source,
            error_class,
            extra={
                "source": self._source,
                "job_id": job.id,
                "attempt": job.attempt,
                "correlation_id": job.correlation_id,
                "error_class": error_class,
            },
        )
        await self._report(job, "error", f"Sync failed: {error_text(exc)}")
        await self._queue.dead_letter(job, error_class)

    async def _report(
        self,
        job: Job,
        status: Literal["ok", "reconnect", "error"],
        message: str,
        events: Sequence[Event] = (),
    ) -> None:
        await self._reports.publish(
            SyncReport(
                id=self._ids.new_id(),
                correlation_id=job.correlation_id,
                source=self._source,
                window=job.window,
                status=status,
                message=safe_message(message),
                at=self._clock.now(),
                events=tuple(events),
                generation=job.generation,
            )
        )

    def _note_failure(self) -> None:
        before = self._breaker.current(self._breaker_state).phase
        self._breaker_state = self._breaker.record_failure(self._breaker_state)
        if self._breaker_state.phase is BreakerPhase.OPEN and before is not BreakerPhase.OPEN:
            logger.warning(
                "circuit opened for %s after %d failures",
                self._source,
                self._breaker_state.failures,
                extra={"source": self._source, "consumer": self._consumer},
            )

    def _note_success(self) -> None:
        if self._breaker_state.phase is not BreakerPhase.CLOSED:
            logger.info("circuit closed for %s", self._source, extra={"source": self._source})
        self._breaker_state = self._breaker.record_success(self._breaker_state)
