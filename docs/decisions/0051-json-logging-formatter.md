# 0051. Structured JSON logging: an allowlisting stdlib formatter

Status: accepted

Context: Decision 0022 named structured JSON logging with a correlation id as its revisit trigger for distributed mode. A job's `correlation_id` must appear in every log line about it, across processes.
Decision:
- `adapters/json_log.py` has `JsonFormatter` (one JSON object per line: `ts` in UTC, `level`, `logger`, `message`, then only these record attributes if present: `correlation_id`, `job_id`, `job_kind`, `source`, `attempt`, `delay_seconds`, `reason`, `consumer`), `job_fields(job)` (the `extra` dict for a job) and `configure_json_logging(level, stream)`.
- An exception is reported as its class name (`exc_type`) only, never its text or traceback, which can embed URLs and credentials. String values are trimmed to 300 characters.
- Only composition roots may call `configure_json_logging` (`app.py`, `workers/__main__.py`, `desktop/main.py`); `tests/test_json_log.py` fails if any other file under `src/` mentions it. Library code just logs.
- The queues log with `extra=job_fields(job)` and the same values in the message text, as 0022 does for services.
- Not wired yet: `app.py` was out of scope for this task and `workers/__main__.py` is still a stub that raises. The first of them to be built calls `configure_json_logging()`.
Alternative: a third-party JSON logging library (new dependency); dumping every `extra` key; a `Logger` port in core.
Reason: stdlib is enough. An allowlist means a secret passed under an unexpected key cannot be emitted. Core has no I/O, so a port would only wrap `logging` for no gain.
Where: `src/command_center/adapters/json_log.py`, `adapters/inprocess_queue.py`, `adapters/queue_redis.py`, `tests/test_json_log.py`.
Revisit when: services need to log a job's correlation id (they would pass `extra` with the same keys), or a field outside the allowlist is needed.
