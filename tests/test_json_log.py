"""The JSON log formatter: correlation id carried, nothing outside the allowlist emitted."""

import io
import json
import logging
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from command_center.adapters.json_log import JsonFormatter, configure_json_logging, job_fields
from queue_support import make_job

SRC = Path(__file__).resolve().parents[1] / "src" / "command_center"
ALLOWED_CALLERS = {
    Path("adapters/json_log.py"),
    Path("app.py"),
    Path("workers/__main__.py"),
    Path("desktop/main.py"),
}


def record(extra: Mapping[str, object] | None = None, message: str = "hello") -> logging.LogRecord:
    made = logging.LogRecord("cc.test", logging.WARNING, __file__, 1, message, None, None)
    for key, value in (extra or {}).items():
        setattr(made, key, value)
    return made


@pytest.fixture
def root_restored() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_a_record_is_one_json_line_with_the_standard_fields() -> None:
    line = JsonFormatter().format(record(message="synced 3 items"))
    data = json.loads(line)
    assert "\n" not in line
    assert (data["level"], data["logger"], data["message"]) == (
        "WARNING",
        "cc.test",
        "synced 3 items",
    )
    assert data["ts"].endswith("+00:00")


def test_the_job_correlation_id_is_carried() -> None:
    job = make_job("j1", "gmail")
    data = json.loads(JsonFormatter().format(record(job_fields(job))))
    assert data["correlation_id"] == "corr-j1"
    assert (data["job_id"], data["source"], data["attempt"]) == ("j1", "gmail", 1)


def test_fields_outside_the_allowlist_are_not_emitted() -> None:
    data = json.loads(
        JsonFormatter().format(record({"token": "fake-secret-value", "password": "x"}))
    )
    assert "token" not in data
    assert "fake-secret-value" not in json.dumps(data)


def test_an_exception_is_reported_by_class_name_only() -> None:
    try:
        msg = "boom with fake-secret-value"
        raise ValueError(msg)  # noqa: TRY301
    except ValueError:
        import sys  # noqa: PLC0415

        made = record()
        made.exc_info = sys.exc_info()
    line = JsonFormatter().format(made)
    assert json.loads(line)["exc_type"] == "ValueError"
    assert "fake-secret-value" not in line


def test_a_long_reason_is_trimmed() -> None:
    data = json.loads(JsonFormatter().format(record({"reason": "y" * 5000})))
    assert len(data["reason"]) == 300


@pytest.mark.usefixtures("root_restored")
def test_configure_json_logging_writes_json_lines_and_replaces_its_own_handler() -> None:
    stream = io.StringIO()
    configure_json_logging(logging.INFO, io.StringIO())
    configure_json_logging(logging.INFO, stream)
    logging.getLogger("cc.test").warning("went wrong", extra=job_fields(make_job("j9")))
    [line] = stream.getvalue().splitlines()
    assert json.loads(line)["correlation_id"] == "corr-j9"


def test_only_composition_roots_configure_logging() -> None:
    callers = {
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if "configure_json_logging" in path.read_text(encoding="utf-8")
    }
    assert callers <= ALLOWED_CALLERS


def test_the_error_class_is_emitted_and_an_error_message_attached_under_another_key_is_not() -> (
    None
):
    data = json.loads(
        JsonFormatter().format(
            record({"error_class": "TransientError", "error": "token fake-secret-value rejected"})
        )
    )
    assert data["error_class"] == "TransientError"
    assert "error" not in data
    assert "fake-secret-value" not in json.dumps(data)
