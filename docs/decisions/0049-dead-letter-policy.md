# 0049. Dead-letter policy

Status: accepted

Context: A job that keeps failing must stop being retried, but its failure must not vanish.
Decision:
- A job is dead-lettered when `fail` is called on its last allowed attempt (`attempt >= max_attempts`) or when its last attempt's visibility timeout expires.
- A dead letter records the job as last delivered, the reason and `failed_at`. The reason is trimmed to 300 characters (`MAX_REASON_LENGTH`); callers pass error text that is already free of secrets (adapters' messages are fixed text), and the queue never adds payloads to it.
- Dead letters are kept until an operator removes them. `list_dead_letters()` is read-only; there is no automatic replay, purge or size cap in this task.
- A Redis stream entry that cannot be parsed into a `Job` (a payload from a different version, a missing field) cannot be dead-lettered, because a dead letter holds a `Job`. It is acked and deleted and logged at ERROR with its entry id and the error class, never the payload. The alternative, leaving it pending, would have every consumer reclaim it forever and starve the queue.
- Dead-lettering is logged at ERROR with the job's correlation id.
Alternative: drop failed jobs after logging; cap or expire the dead-letter list; replay automatically on a timer.
Reason: A sync that fails five times with backoff is not fixed by a sixth try, and silently dropping it hides a broken source. At personal scale an unbounded list is a handful of entries. Automatic replay would just repeat the failure.
Where: `adapters/inprocess_queue.py` (`_dead_letter`), `adapters/queue_redis.py` (`{prefix}:jobs:dead` stream), `tests/test_job_queue_contract.py`.
Revisit when: a user-facing view of failed syncs, replay or purge is built, or the dead-letter stream grows without bound (add a cap).
