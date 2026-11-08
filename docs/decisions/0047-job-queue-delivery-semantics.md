# 0047. Job queue delivery semantics: at-least-once, one async lane

Status: accepted

Context: Task 3a adds the `JobQueue` port (`core/ports.py`) with an in-process queue and a Redis Streams queue (decision 0001). Both must behave the same, so one contract suite runs against both.
Decision:
- Delivery is at-least-once. A consumed job that is not acked within the visibility timeout is delivered again with `attempt + 1`. Handlers must be idempotent (`EventStore.replace` already is, decision 0028).
- The port is async (`publish`, `consume`, `ack`, `fail`, `list_dead_letters`). `consume(group, consumer, block_ms)` waits at most `block_ms` (0 = do not wait) and returns `None` when nothing is ready.
- The queue is one work lane. `group` is the Redis consumer-group name (use one per deployment); the in-process queue accepts and ignores `group` and `consumer`. Because an acked Redis entry is deleted (`XDEL`) to bound memory, two groups on one queue would not each see every job.
- Ordering: jobs are first delivered in publish order, so one source's jobs arrive in order. A retried or redelivered job can arrive after later jobs of its source; ordering is not kept across failures.
- `ack` and `fail` act on the delivery the queue holds, not on the `Job` the caller passes, so a `fail` from a superseded delivery requeues the live delivery's next attempt. `ack` and `fail` for a job that is not in flight (already acked, dead-lettered, or never delivered) are no-ops. A late `ack` from a superseded delivery still completes the job, because the work was done. A `fail` from a superseded delivery while another delivery is live also takes effect; that is another duplicate, which at-least-once allows.
- Retries wait in a delay set: a heap in memory, a sorted set (`{prefix}:jobs:delayed`, scored in ms of the queue's `Clock`) in Redis, moved onto the stream at the start of the next `consume`. A consumer already blocked in `XREADGROUP` sees a due retry on its next call, so retry latency can exceed the delay by up to `block_ms`.
- The Redis queue remembers each delivery's stream entry id in the consuming process. An `ack` or `fail` sent to a different process is a no-op and the job is redelivered after the timeout.
- Publishing the same job id twice is not deduplicated; ids come from an `IdSource` and are unique.
Alternative: a synchronous port like the stores (0016); exactly-once; one stream per source with the consumer group naming the source.
Reason: Workers are async, and a blocking `consume` on a sync port would stall the event loop or need a thread per consumer; redis-py has a native async client. Exactly-once is not achievable across a crash. One stream per source needs the port to know the source list, which this task does not have, and the card fixes the signature `consume(group, consumer, block_ms)`.
Where: `src/command_center/core/ports.py` (`JobQueue`), `adapters/inprocess_queue.py`, `adapters/queue_redis.py`, `tests/test_job_queue_contract.py`.
Revisit when: the worker task needs one consumer per source (add a stream per source), a second consumer group is needed, or retry latency matters (promote from a timer).
