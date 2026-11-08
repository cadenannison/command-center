"""Structured JSON logging that carries a job's correlation id. Decision: docs/decisions/0051."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO

from command_center.core.jobs import MAX_REASON_LENGTH, Job
from command_center.core.redact import trim

# Allowlist: a record's other attributes (args, exc_text, anything a caller attached) never reach
# the output, so a secret that slips into `extra` under another name cannot be emitted.
LOG_FIELDS = (
    "correlation_id",
    "job_id",
    "job_kind",
    "source",
    "attempt",
    "delay_seconds",
    "reason",
    "consumer",
)

_HANDLER_MARK = "_command_center_json_handler"


def job_fields(job: Job) -> dict[str, object]:
    """Return the `extra` fields that identify job in a log record."""
    return {
        "correlation_id": job.correlation_id,
        "job_id": job.id,
        "job_kind": job.kind,
        "source": job.source,
        "attempt": job.attempt,
    }


class JsonFormatter(logging.Formatter):
    """Format a record as one JSON line: time, level, logger, message and allowlisted fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in LOG_FIELDS:
            if hasattr(record, name):
                payload[name] = _json_safe(getattr(record, name))
        if record.exc_info is not None and record.exc_info[0] is not None:
            # The class name only: a traceback or exception text can embed URLs and credentials.
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _json_safe(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    return trim(str(value), MAX_REASON_LENGTH)


def configure_json_logging(
    level: int = logging.INFO, stream: TextIO | None = None
) -> logging.Handler:
    """Send root-logger output to stream (default stderr) as JSON lines; safe to call twice.

    Composition roots call this once at startup; nothing else may (tests/test_json_log.py).
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(level)
    return handler
