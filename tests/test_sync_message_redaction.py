"""Sync messages kept in state are redacted and trimmed before they are stored or returned."""

from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from builders import NOW
from command_center.api import create_app
from command_center.core.errors import FatalError, TransientError
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

EMAIL = "someone.private@example.com"
DIGITS = "4155550123456"
LEAKY = f"account {EMAIL} rejected request 9876543210 (card {DIGITS})"
CRED = "fake-canvas-token-ABCD1234"
LOCAL = "http://localhost"


def make_sync(adapter: FakeAdapter) -> tuple[SyncService, InMemorySecretStore]:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", CRED)
    sync = SyncService(
        {adapter.name: adapter},
        secrets,
        InMemoryEventStore(),
        FakeClock(NOW),
        sleep=RecordingSleep(),
    )
    return sync, secrets


@pytest.mark.parametrize(
    "error",
    [FatalError(LEAKY), TransientError(LEAKY)],
    ids=["fatal", "transient"],
)
async def test_an_adapter_error_message_is_redacted_in_the_returned_and_remembered_state(
    error: Exception,
) -> None:
    sync, _ = make_sync(FakeAdapter(script=[error]))

    returned = await sync.sync("canvas")
    remembered = sync.state("canvas")

    assert remembered == returned
    assert returned.status == "error"
    for text in (EMAIL, "9876543210", DIGITS):
        assert text not in returned.message
    assert "[email]" in returned.message
    assert "[number]" in returned.message


async def test_a_long_message_is_cut_to_200_characters_after_redaction() -> None:
    sync, _ = make_sync(FakeAdapter(script=[FatalError("x" * 500)]))

    state = await sync.sync("canvas")

    assert len(state.message) == 200
    assert state.message.endswith("…")


async def test_a_digit_run_straddling_the_cut_is_redacted_whole() -> None:
    # Redact before trim: cutting first would leave a partial digit run that no longer matches.
    sync, _ = make_sync(FakeAdapter(script=[FatalError("x" * 150 + " " + "1" * 40)]))

    state = await sync.sync("canvas")

    assert "1111" not in state.message
    assert len(state.message) <= 200


async def test_a_recorded_error_state_is_redacted_too() -> None:
    sync, _ = make_sync(FakeAdapter())

    state = sync.record_error("canvas", LEAKY)

    assert EMAIL not in state.message
    assert DIGITS not in state.message
    assert sync.state("canvas") == state


async def test_ordinary_messages_are_unchanged() -> None:
    sync, _ = make_sync(FakeAdapter())

    state = await sync.sync("canvas")

    assert state.message == "Synced 0 items"


def test_get_settings_never_shows_the_email_or_digits_from_an_adapter_error() -> None:
    adapter = FakeAdapter(script=[FatalError(LEAKY)])
    secrets = InMemorySecretStore()
    events = InMemoryEventStore()
    clock = FakeClock(NOW)
    adapters = {adapter.name: adapter}
    sync = SyncService(adapters, secrets, events, clock, sleep=RecordingSleep())
    container = Container(
        sync=sync,
        agenda=AgendaService(events, clock, ZoneInfo("America/Denver")),
        settings=SettingsService(adapters, secrets, sync),
    )
    client = TestClient(create_app(container), base_url=LOCAL)

    put = client.put("/v1/settings/canvas", json={"credentials": {"token": CRED}})
    body = client.get("/v1/settings").text

    assert put.status_code == 200
    assert '"status":"error"' in body.replace(" ", "")
    for text in (EMAIL, "9876543210", DIGITS):
        assert text not in body


@pytest.mark.parametrize("error_type", [FatalError, TransientError], ids=["fatal", "transient"])
async def test_redaction_sees_the_whole_error_text_before_any_cut(
    error_type: type[Exception],
) -> None:
    # Redacting the first run shortens the text, which pulls the tail of a longer one into the
    # 200-character window: the tail must be judged as the whole number it is, not as a stub.
    text = "1" * 50 + " " + "a" * 143 + " 1234567"
    sync, _ = make_sync(FakeAdapter(script=[error_type(text)]))

    state = await sync.sync("canvas")

    assert "12345" not in state.message
    assert state.message.endswith("[number]")
