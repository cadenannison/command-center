"""Adapter text never reaches a log record unredacted (decision 0052, extended to logs)."""

import logging

import pytest

from builders import NOW
from command_center.core.errors import FatalError, TransientError
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

EMAIL = "someone.private@example.com"
DIGITS = "4155550123456"
LEAKY = f"account {EMAIL} rejected request {DIGITS}"
LOGGER = "command_center.services.sync"


def make_sync(adapter: FakeAdapter) -> SyncService:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-canvas-token-ABCD1234")
    return SyncService(
        {adapter.name: adapter},
        secrets,
        InMemoryEventStore(),
        FakeClock(NOW),
        sleep=RecordingSleep(),
    )


def everything_logged(records: list[logging.LogRecord]) -> str:
    """The rendered message and every attribute of each record, so an `extra` field counts too."""
    return "\n".join(f"{record.getMessage()}\n{record.__dict__!r}" for record in records)


@pytest.mark.parametrize(
    "script",
    [
        [FatalError(LEAKY)],
        [TransientError(LEAKY)],
        [TransientError("timeout"), FatalError(LEAKY)],
    ],
    ids=["fatal", "transient-retries-then-gives-up", "retry-then-fatal"],
)
async def test_an_adapter_error_text_is_redacted_in_every_log_record(
    script: list[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await make_sync(FakeAdapter(script=script)).sync("canvas")

    logged = everything_logged(caplog.records)
    assert caplog.records
    assert EMAIL not in logged
    assert DIGITS not in logged
    assert EMAIL not in caplog.text
    assert DIGITS not in caplog.text


async def test_a_retry_log_keeps_the_source_and_attempt_with_a_redacted_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await make_sync(FakeAdapter(script=[TransientError(LEAKY), []])).sync("canvas")

    (record,) = caplog.records
    assert record.__dict__["source"] == "canvas"
    assert record.__dict__["attempt"] == 1
    assert record.__dict__["reason"] == "account [email] rejected request [number]"
    assert "[email]" in record.getMessage()
    assert "[number]" in record.getMessage()


async def test_a_logged_reason_is_cut_to_200_characters_after_redaction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = "x" * 150 + " " + "1" * 40
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        await make_sync(FakeAdapter(script=[FatalError(text)])).sync("canvas")

    (record,) = caplog.records
    assert "1111" not in everything_logged([record])
    assert len(record.getMessage()) <= len("sync of canvas failed: ") + 200
