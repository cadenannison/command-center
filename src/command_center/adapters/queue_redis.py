"""Redis Streams JobQueue for distributed mode (the only importer of redis).

Decisions: 0047 (delivery), 0048 (defaults), 0049 (dead letters), 0050 (file name).
Keys: `{prefix}:jobs` (stream), `{prefix}:jobs:delayed` (sorted set of retries by ready time in
ms), `{prefix}:jobs:dead` (stream); the prefix is a hash tag so all three share one cluster slot.
The queue is one work lane: use one consumer group per deployment, because an acked entry is
deleted from the stream.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Self, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from command_center.adapters.json_log import job_fields
from command_center.core.jobs import (
    MAX_REASON_LENGTH,
    VISIBILITY_TIMEOUT_REASON,
    DeadLetter,
    DeadReport,
    Job,
    SyncReport,
)
from command_center.core.ports import Clock, Rng
from command_center.core.redact import trim
from command_center.core.resilience import (
    DEFAULT_RETRY_POLICY,
    DEFAULT_VISIBILITY_TIMEOUT,
    RetryPolicy,
)

logger = logging.getLogger(__name__)

# Moves due retries onto the stream in one atomic step, so a crash cannot lose or duplicate one.
_PROMOTE = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 100)
for _, member in ipairs(due) do
  redis.call('XADD', KEYS[2], '*', 'job', member)
  redis.call('ZREM', KEYS[1], member)
end
return #due
"""

# Finishes a failed delivery: nothing happens unless the entry is still pending, so a stale
# fail cannot resurrect an acked job. ARGV: group, entry id, mode, payload, ready_at_ms.
_RESOLVE = """
if redis.call('XACK', KEYS[1], ARGV[1], ARGV[2]) == 0 then return 0 end
redis.call('XDEL', KEYS[1], ARGV[2])
if ARGV[3] == 'dead' then
  redis.call('XADD', KEYS[3], '*', 'dead', ARGV[4])
else
  redis.call('ZADD', KEYS[2], ARGV[5], ARGV[4])
end
return 1
"""


def source_queue_prefix(source: str) -> str:
    """The Redis key prefix of one source's job queue: one queue per source (decision 0070).

    The api, the scheduler and the workers must agree on it, so it lives here, once.
    """
    return f"cc-{source}"


@dataclass(frozen=True)
class _Raw:
    entry_id: str
    fields: dict[str, str]
    deliveries: int


@dataclass(frozen=True)
class _Delivery:
    group: str
    entry_id: str
    job: Job


class RedisStreamsQueue:
    """JobQueue over Redis Streams: XADD, XREADGROUP, XACK, and XAUTOCLAIM for redelivery."""

    def __init__(  # noqa: PLR0913
        self,
        client: Redis,
        clock: Clock,
        rng: Rng,
        *,
        prefix: str = "cc",
        policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        visibility_timeout: timedelta = DEFAULT_VISIBILITY_TIMEOUT,
    ) -> None:
        self._client = client
        self._clock = clock
        self._rng = rng
        self._policy = policy
        self._visibility_ms = int(visibility_timeout.total_seconds() * 1000)
        self._stream = f"{{{prefix}}}:jobs"
        self._delayed = f"{{{prefix}}}:jobs:delayed"
        self._dead = f"{{{prefix}}}:jobs:dead"
        self._groups: set[str] = set()
        # Deliveries live in this process: an ack from another process is a no-op and the job is
        # redelivered after the visibility timeout. fail() acts on the held delivery, like the
        # in-process queue, not on the (possibly superseded) job the caller passes.
        self._entries: dict[str, _Delivery] = {}

    @classmethod
    def from_url(  # noqa: PLR0913
        cls,
        url: str,
        clock: Clock,
        rng: Rng,
        *,
        prefix: str = "cc",
        policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        visibility_timeout: timedelta = DEFAULT_VISIBILITY_TIMEOUT,
    ) -> Self:
        """Build a queue and its client; composition roots call this instead of importing redis."""
        client = Redis.from_url(url, decode_responses=True, protocol=2)  # pyright: ignore[reportUnknownMemberType]
        return cls(
            client, clock, rng, prefix=prefix, policy=policy, visibility_timeout=visibility_timeout
        )

    async def aclose(self) -> None:
        """Close the Redis connection."""
        await self._client.aclose()

    async def publish(self, job: Job) -> None:
        await self._client.xadd(self._stream, {"job": job.model_dump_json()})
        logger.info("job published", extra=job_fields(job))

    async def consume(self, group: str, consumer: str, block_ms: int) -> Job | None:
        await self._ensure_group(group)
        await self._promote_due()
        # Each pass resolves or returns one entry, so the loop ends when the stream is drained.
        while True:
            raw = await self._claim_stale(group, consumer) or await self._read_new(
                group, consumer, block_ms
            )
            if raw is None:
                return None
            stored = self._parse(raw)
            if stored is None:
                await self._discard(group, raw.entry_id)
                continue
            # A delivery count above 1 means earlier deliveries timed out; each is an attempt.
            job = stored.model_copy(update={"attempt": stored.attempt + raw.deliveries - 1})
            if job.attempt > self._policy.max_attempts:
                held = job.model_copy(update={"attempt": self._policy.max_attempts})
                await self._resolve(group, raw.entry_id, held, VISIBILITY_TIMEOUT_REASON, dead=True)
                continue
            if raw.deliveries > 1:
                logger.warning(
                    "job redelivered after visibility timeout",
                    extra={**job_fields(job), "reason": "visibility timeout", "consumer": consumer},
                )
            self._entries[job.id] = _Delivery(group, raw.entry_id, job)
            return job

    async def ack(self, job: Job) -> None:
        delivery = self._entries.pop(job.id, None)
        if delivery is None:
            logger.debug("ack ignored: job not in flight", extra=job_fields(job))
            return
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xack(self._stream, delivery.group, delivery.entry_id)
            pipe.xdel(self._stream, delivery.entry_id)
            await pipe.execute()

    async def fail(self, job: Job, reason: str) -> None:
        delivery = self._entries.pop(job.id, None)
        if delivery is None:
            logger.debug("fail ignored: job not in flight", extra=job_fields(job))
            return
        reason = trim(reason, MAX_REASON_LENGTH)
        dead = self._policy.exhausted(delivery.job.attempt)
        await self._resolve(delivery.group, delivery.entry_id, delivery.job, reason, dead=dead)

    async def dead_letter(self, job: Job, reason: str) -> None:
        delivery = self._entries.pop(job.id, None)
        if delivery is None:
            logger.debug("dead_letter ignored: job not in flight", extra=job_fields(job))
            return
        reason = trim(reason, MAX_REASON_LENGTH)
        await self._resolve(delivery.group, delivery.entry_id, delivery.job, reason, dead=True)

    async def list_dead_letters(self) -> list[DeadLetter]:
        rows = cast("list[tuple[str, dict[str, str]]]", await self._client.xrange(self._dead) or [])
        return [DeadLetter.model_validate_json(fields["dead"]) for _, fields in rows]

    async def _resolve(
        self, group: str, entry_id: str, job: Job, reason: str, *, dead: bool
    ) -> None:
        now = self._clock.now()
        if dead:
            payload = DeadLetter(job=job, reason=reason, failed_at=now).model_dump_json()
            ready_ms = 0
        else:
            delay = self._policy.delay(job.attempt, self._rng)
            payload = job.next_attempt().model_dump_json()
            ready_ms = int((now + delay).timestamp() * 1000)
        script = self._client.register_script(_RESOLVE)
        resolved = await script(
            keys=[self._stream, self._delayed, self._dead],
            args=[group, entry_id, "dead" if dead else "retry", payload, ready_ms],
        )
        if not resolved:
            logger.debug("fail ignored: entry no longer pending", extra=job_fields(job))
        elif dead:
            logger.error(
                "job dead-lettered: %s", reason, extra={**job_fields(job), "reason": reason}
            )
        else:
            logger.warning(
                "job failed, will retry: %s",
                reason,
                extra={**job_fields(job), "reason": reason},
            )

    def _parse(self, raw: _Raw) -> Job | None:
        try:
            return Job.model_validate_json(raw.fields["job"])
        except (KeyError, ValueError) as error:
            # Never log the payload or the validation text: both can echo job content.
            # logger.error, not .exception: the traceback can echo the payload.
            logger.error(  # noqa: TRY400
                "discarding unreadable queue entry %s (%s)",
                raw.entry_id,
                type(error).__name__,
                extra={"reason": f"unreadable entry: {type(error).__name__}"},
            )
            return None

    async def _discard(self, group: str, entry_id: str) -> None:
        # An entry that cannot be parsed has no Job to dead-letter; left pending it would be
        # reclaimed by every consumer forever and starve the queue (decision 0049).
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xack(self._stream, group, entry_id)
            pipe.xdel(self._stream, entry_id)
            await pipe.execute()

    async def _ensure_group(self, group: str) -> None:
        if group in self._groups:
            return
        try:
            # id "0" so jobs published before the first consumer started are still delivered.
            await self._client.xgroup_create(self._stream, group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._groups.add(group)

    async def _in_group[T](self, group: str, call: Callable[[], Awaitable[T]]) -> T:
        """Run call; if Redis lost the group (restart, flush), recreate it and retry once."""
        try:
            return await call()
        except ResponseError as error:
            if "NOGROUP" not in str(error):
                raise
            logger.warning("consumer group missing, recreating it", extra={"reason": "NOGROUP"})
            self._groups.discard(group)
            await self._ensure_group(group)
            return await call()

    async def _promote_due(self) -> None:
        script = self._client.register_script(_PROMOTE)
        now_ms = int(self._clock.now().timestamp() * 1000)
        await script(keys=[self._delayed, self._stream], args=[now_ms])

    async def _claim_stale(self, group: str, consumer: str) -> _Raw | None:
        # count=1 so one stale entry is claimed (the rest stay claimable by other consumers);
        # Redis inspects only a few pending entries per call, so follow the cursor to the end.
        cursor = "0-0"
        while True:
            reply = await self._in_group(
                group,
                lambda start=cursor: self._autoclaim(group, consumer, start),
            )
            cursor = str(reply[0])
            for entry_id, fields in cast("list[tuple[str, dict[str, str]]]", reply[1]):
                pending = cast(
                    "list[dict[str, Any]]",
                    await self._client.xpending_range(self._stream, group, entry_id, entry_id, 1),
                )
                if not pending:
                    continue  # acked or resolved by someone else since the claim
                # XAUTOCLAIM counted this claim in times_delivered.
                return _Raw(entry_id, fields, int(pending[0]["times_delivered"]))
            if cursor == "0-0":
                return None

    async def _autoclaim(self, group: str, consumer: str, start: str) -> list[Any]:
        return await self._client.xautoclaim(
            self._stream, group, consumer, self._visibility_ms, start_id=start, count=1
        )

    async def _read_new(self, group: str, consumer: str, block_ms: int) -> _Raw | None:
        reply = await self._in_group(group, lambda: self._readgroup(group, consumer, block_ms))
        if not reply:
            return None
        entry_id, fields = cast("tuple[str, dict[str, str]]", reply[0][1][0])
        return _Raw(entry_id, fields, 1)

    async def _readgroup(self, group: str, consumer: str, block_ms: int) -> list[Any] | None:
        # redis-py treats block=0 as "wait forever"; the port treats 0 as "do not wait".
        reply = await self._client.xreadgroup(
            group,
            consumer,
            {self._stream: ">"},
            count=1,
            block=block_ms if block_ms > 0 else None,
        )
        return cast("list[Any] | None", reply)


DEFAULT_MAX_DELIVERIES = 5
DELIVERIES_EXHAUSTED_REASON = "delivered too many times without an ack"


@dataclass(frozen=True)
class _Held:
    group: str
    entry_id: str
    report: SyncReport


class RedisReportStream:
    """ReportStream over Redis Streams (decision 0071).

    Keys `{prefix}:reports` and `{prefix}:reports:dead`. Like the job queue, an acked entry is
    deleted, entry ids are held in the consuming process, and an unacked report returns after the
    visibility timeout. A report delivered `max_deliveries` times without an ack is dead-lettered
    (as a `DeadReport`, without its events) instead of looping forever.
    """

    def __init__(
        self,
        client: Redis,
        clock: Clock,
        *,
        prefix: str = "cc",
        visibility_timeout: timedelta = DEFAULT_VISIBILITY_TIMEOUT,
        max_deliveries: int = DEFAULT_MAX_DELIVERIES,
    ) -> None:
        self._client = client
        self._clock = clock
        self._visibility_ms = int(visibility_timeout.total_seconds() * 1000)
        self._max_deliveries = max_deliveries
        self._stream = f"{{{prefix}}}:reports"
        self._dead = f"{{{prefix}}}:reports:dead"
        self._groups: set[str] = set()
        self._held: dict[str, _Held] = {}

    @classmethod
    def from_url(
        cls,
        url: str,
        clock: Clock,
        *,
        prefix: str = "cc",
        visibility_timeout: timedelta = DEFAULT_VISIBILITY_TIMEOUT,
        max_deliveries: int = DEFAULT_MAX_DELIVERIES,
    ) -> Self:
        """Build a stream and its client; composition roots call this instead of importing redis."""
        client = Redis.from_url(url, decode_responses=True, protocol=2)  # pyright: ignore[reportUnknownMemberType]
        return cls(
            client,
            clock,
            prefix=prefix,
            visibility_timeout=visibility_timeout,
            max_deliveries=max_deliveries,
        )

    async def aclose(self) -> None:
        """Close the Redis connection."""
        await self._client.aclose()

    async def publish(self, report: SyncReport) -> None:
        await self._client.xadd(self._stream, {"report": report.model_dump_json()})
        logger.info(
            "report published",
            extra={"correlation_id": report.correlation_id, "source": report.source},
        )

    async def consume(self, group: str, consumer: str, block_ms: int) -> SyncReport | None:
        await self._ensure_group(group)
        while True:
            raw = await self._claim_stale(group, consumer) or await self._read_new(
                group, consumer, block_ms
            )
            if raw is None:
                return None
            report = self._parse(raw)
            if report is None:
                await self._remove(group, raw.entry_id)
                continue
            if raw.deliveries > self._max_deliveries:
                await self._give_up(group, raw.entry_id, report, DELIVERIES_EXHAUSTED_REASON)
                continue
            self._held[report.id] = _Held(group, raw.entry_id, report)
            return report

    async def ack(self, report: SyncReport) -> None:
        held = self._held.pop(report.id, None)
        if held is None:
            return
        await self._remove(held.group, held.entry_id)

    async def dead_letter(self, report: SyncReport, reason: str) -> None:
        held = self._held.pop(report.id, None)
        if held is None:
            return
        await self._give_up(held.group, held.entry_id, held.report, trim(reason, MAX_REASON_LENGTH))

    async def list_dead_reports(self) -> list[DeadReport]:
        rows = cast("list[tuple[str, dict[str, str]]]", await self._client.xrange(self._dead) or [])
        return [DeadReport.model_validate_json(fields["dead"]) for _, fields in rows]

    async def _give_up(self, group: str, entry_id: str, report: SyncReport, reason: str) -> None:
        note = DeadReport(
            id=report.id,
            correlation_id=report.correlation_id,
            source=report.source,
            reason=reason,
            failed_at=self._clock.now(),
        )
        script = self._client.register_script(_RESOLVE)
        resolved = await script(
            keys=[self._stream, self._dead, self._dead],
            args=[group, entry_id, "dead", note.model_dump_json(), 0],
        )
        if resolved:
            logger.error(
                "report dead-lettered: %s",
                reason,
                extra={
                    "correlation_id": report.correlation_id,
                    "source": report.source,
                    "reason": reason,
                },
            )

    async def _remove(self, group: str, entry_id: str) -> None:
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xack(self._stream, group, entry_id)
            pipe.xdel(self._stream, entry_id)
            await pipe.execute()

    def _parse(self, raw: _Raw) -> SyncReport | None:
        try:
            return SyncReport.model_validate_json(raw.fields["report"])
        except (KeyError, ValueError) as error:
            # Never log the payload or the validation text: both can echo events.
            logger.error(  # noqa: TRY400
                "discarding unreadable report entry %s (%s)",
                raw.entry_id,
                type(error).__name__,
                extra={"reason": f"unreadable entry: {type(error).__name__}"},
            )
            return None

    async def _ensure_group(self, group: str) -> None:
        if group in self._groups:
            return
        try:
            await self._client.xgroup_create(self._stream, group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._groups.add(group)

    async def _in_group[T](self, group: str, call: Callable[[], Awaitable[T]]) -> T:
        """Run call; if Redis lost the group (restart, flush), recreate it and retry once."""
        try:
            return await call()
        except ResponseError as error:
            if "NOGROUP" not in str(error):
                raise
            logger.warning("consumer group missing, recreating it", extra={"reason": "NOGROUP"})
            self._groups.discard(group)
            await self._ensure_group(group)
            return await call()

    async def _claim_stale(self, group: str, consumer: str) -> _Raw | None:
        cursor = "0-0"
        while True:
            reply = await self._in_group(
                group,
                lambda start=cursor: self._client.xautoclaim(
                    self._stream, group, consumer, self._visibility_ms, start_id=start, count=1
                ),
            )
            cursor = str(reply[0])
            for entry_id, fields in cast("list[tuple[str, dict[str, str]]]", reply[1]):
                pending = cast(
                    "list[dict[str, Any]]",
                    await self._client.xpending_range(self._stream, group, entry_id, entry_id, 1),
                )
                if pending:
                    return _Raw(entry_id, fields, int(pending[0]["times_delivered"]))
            if cursor == "0-0":
                return None

    async def _read_new(self, group: str, consumer: str, block_ms: int) -> _Raw | None:
        # redis-py treats block=0 as "wait forever"; the port treats 0 as "do not wait".
        reply = cast(
            "list[Any] | None",
            await self._in_group(
                group,
                lambda: self._client.xreadgroup(
                    group,
                    consumer,
                    {self._stream: ">"},
                    count=1,
                    block=block_ms if block_ms > 0 else None,
                ),
            ),
        )
        if not reply:
            return None
        entry_id, fields = cast("tuple[str, dict[str, str]]", reply[0][1][0])
        return _Raw(entry_id, fields, 1)
