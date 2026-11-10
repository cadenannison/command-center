"""ConnectResult.message is redacted and trimmed like a sync message (decision 0052)."""

from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from builders import NOW
from command_center.api import create_app
from command_center.core.errors import FatalError, TransientError
from command_center.core.schema import ValidationResult
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

EMAIL = "someone.private@example.com"
DIGITS = "4155550123456"
LEAKY = f"account {EMAIL} rejected request (card {DIGITS})"
CRED = "fake-canvas-token-ABCD1234"
LOCAL = "http://localhost"


def make_container(adapter: FakeAdapter) -> Container:
    secrets = InMemorySecretStore()
    events = InMemoryEventStore()
    clock = FakeClock(NOW)
    adapters = {adapter.name: adapter}
    sync = SyncService(adapters, secrets, events, clock, sleep=RecordingSleep())
    return Container(
        sync=sync,
        agenda=AgendaService(events, clock, ZoneInfo("America/Denver")),
        settings=SettingsService(adapters, secrets, sync),
    )


def assert_clean(text: str) -> None:
    assert EMAIL not in text
    assert DIGITS not in text


@pytest.mark.parametrize(
    "adapter",
    [
        FakeAdapter(validation=ValidationResult(ok=False, message=LEAKY)),
        FakeAdapter(validation=ValidationResult(ok=True, message=LEAKY)),
        FakeAdapter(validate_error=FatalError(LEAKY)),
        FakeAdapter(validate_error=TransientError(LEAKY)),
    ],
    ids=["rejected", "accepted", "fatal", "transient"],
)
async def test_a_validation_message_is_redacted(adapter: FakeAdapter) -> None:
    container = make_container(adapter)

    result = await container.settings.connect("canvas", {"token": CRED})

    assert_clean(result.message)
    assert "[email]" in result.message
    assert "[number]" in result.message


async def test_a_long_validation_message_is_cut_to_200_characters() -> None:
    adapter = FakeAdapter(validation=ValidationResult(ok=False, message="x " * 250))
    container = make_container(adapter)

    result = await container.settings.connect("canvas", {"token": CRED})

    assert len(result.message) == 200
    assert result.message.endswith("…")


async def test_the_prefix_of_a_validation_failure_counts_towards_the_limit() -> None:
    container = make_container(FakeAdapter(validate_error=FatalError("x " * 250)))

    result = await container.settings.connect("canvas", {"token": CRED})

    assert result.message.startswith("Could not validate credentials: ")
    assert len(result.message) == 200


async def test_ordinary_connect_messages_are_unchanged() -> None:
    container = make_container(FakeAdapter())

    result = await container.settings.connect("canvas", {"token": CRED})

    assert result.message == "Connected"


def test_put_settings_never_returns_the_email_or_digits_from_an_adapter_message() -> None:
    adapter = FakeAdapter(validation=ValidationResult(ok=False, message=LEAKY))
    client = TestClient(create_app(make_container(adapter)), base_url=LOCAL)

    response = client.put("/v1/settings/canvas", json={"credentials": {"token": CRED}})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert_clean(response.text)


async def test_redaction_sees_the_whole_validation_error_text_before_any_cut() -> None:
    text = "1" * 50 + " " + "a" * 143 + " 1234567"
    container = make_container(FakeAdapter(validate_error=FatalError(text)))

    result = await container.settings.connect("canvas", {"token": CRED})

    assert "12345" not in result.message
    assert result.message.endswith("[number]")
