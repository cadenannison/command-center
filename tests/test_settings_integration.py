"""SettingsService with a credential-only integration: same write-only flow, no sync, no events."""

from collections.abc import Mapping

import pytest

from builders import NOW
from command_center.core.errors import FatalError, TransientError
from command_center.core.schema import ValidationResult
from command_center.services.errors import UnknownSourceError
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import KEYCHAIN_DETAIL, FakeAdapter, RecordingSleep, UnavailableSecretStore
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

KEY = "fake-gemini-key-ABCD1234"


class FakeIntegration:
    """A scripted IntegrationAdapter: it has `validate` and, like the real one, no `fetch`."""

    def __init__(
        self, *, result: ValidationResult | None = None, error: Exception | None = None
    ) -> None:
        self._result = result or ValidationResult(ok=True, message="Key accepted")
        self._error = error
        self.validations: list[Mapping[str, str]] = []

    @property
    def name(self) -> str:
        return "gemini"

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        self.validations.append(dict(creds))
        if self._error is not None:
            raise self._error
        return self._result


class Rig:
    def __init__(
        self,
        integration: FakeIntegration | None = None,
        secrets: InMemorySecretStore | UnavailableSecretStore | None = None,
    ) -> None:
        self.integration = integration or FakeIntegration()
        self.secrets = secrets if secrets is not None else InMemorySecretStore()
        self.canvas = FakeAdapter("canvas")
        self.events = InMemoryEventStore()
        self.sync = SyncService(
            {"canvas": self.canvas},
            self.secrets,
            self.events,
            FakeClock(NOW),
            sleep=RecordingSleep(),
        )
        self.settings = SettingsService(
            {"canvas": self.canvas}, self.secrets, self.sync, {"gemini": self.integration}
        )


async def test_the_integration_is_listed_after_the_sources_with_no_sync_state() -> None:
    rig = Rig()

    listed = await rig.settings.status()

    assert [(item.source, item.keys, item.sync) for item in listed] == [
        ("canvas", {}, None),
        ("gemini", {}, None),
    ]


async def test_connect_validates_stores_and_returns_no_sync_state() -> None:
    rig = Rig()

    result = await rig.settings.connect("gemini", {"api_key": KEY})

    assert rig.integration.validations == [{"api_key": KEY}]
    assert dict(rig.secrets.get("gemini")) == {"api_key": KEY}
    assert (result.ok, result.message, result.sync) == (True, "Key accepted", None)
    assert rig.sync.state("gemini") is None


async def test_status_is_write_only_set_and_last4() -> None:
    rig = Rig()
    await rig.settings.connect("gemini", {"api_key": KEY})

    gemini = (await rig.settings.status())[1]

    assert (gemini.source, gemini.sync) == ("gemini", None)
    assert gemini.keys["api_key"].set is True
    assert gemini.keys["api_key"].last4 == "1234"
    assert KEY not in gemini.model_dump_json()


async def test_a_blank_key_keeps_the_stored_one_and_the_merged_set_is_validated() -> None:
    rig = Rig()
    await rig.settings.connect("gemini", {"api_key": KEY})

    await rig.settings.connect("gemini", {"api_key": "  "})

    assert rig.integration.validations[-1] == {"api_key": KEY}
    assert dict(rig.secrets.get("gemini")) == {"api_key": KEY}


async def test_a_rejected_key_is_ok_false_and_nothing_is_stored() -> None:
    rig = Rig(FakeIntegration(result=ValidationResult(ok=False, message="Gemini rejected the key")))

    result = await rig.settings.connect("gemini", {"api_key": KEY})

    assert (result.ok, result.message) == (False, "Gemini rejected the key")
    assert dict(rig.secrets.get("gemini")) == {}


@pytest.mark.parametrize("error", [TransientError("Gemini is unreachable"), FatalError("odd")])
async def test_a_validate_failure_is_ok_false_with_a_prefixed_message_and_nothing_stored(
    error: Exception,
) -> None:
    rig = Rig(FakeIntegration(error=error))

    result = await rig.settings.connect("gemini", {"api_key": KEY})

    assert result.ok is False
    assert result.message.startswith("Could not validate credentials: ")
    assert dict(rig.secrets.get("gemini")) == {}


async def test_failure_messages_are_redacted_and_bounded() -> None:
    noisy = f"rejected for someone@example.com, code 123456789 {'x' * 400}"
    rig = Rig(FakeIntegration(result=ValidationResult(ok=False, message=noisy)))

    result = await rig.settings.connect("gemini", {"api_key": KEY})

    assert "someone@example.com" not in result.message
    assert "123456789" not in result.message
    assert len(result.message) <= 200


async def test_the_secret_store_being_down_is_a_fixed_message_that_remembers_no_sync_state() -> (
    None
):
    rig = Rig(secrets=UnavailableSecretStore())

    result = await rig.settings.connect("gemini", {"api_key": KEY})

    assert (result.ok, result.message) == (False, "secret store unavailable")
    assert KEYCHAIN_DETAIL not in result.model_dump_json()
    assert rig.sync.state("gemini") is None
    assert rig.integration.validations == []


async def test_status_reports_an_unavailable_store_as_an_error_state_without_keys() -> None:
    rig = Rig(secrets=UnavailableSecretStore())

    gemini = (await rig.settings.status())[1]

    assert gemini.keys == {}
    assert gemini.sync is not None
    assert (gemini.sync.status, gemini.sync.message) == ("error", "secret store unavailable")
    assert rig.sync.state("gemini") is None


async def test_disconnect_deletes_the_key_and_leaves_every_source_alone() -> None:
    rig = Rig()
    await rig.settings.connect("gemini", {"api_key": KEY})
    rig.secrets.set("canvas", "token", "fake-canvas-token-1234")

    result = await rig.settings.disconnect("gemini")

    assert (result.source, result.keys, result.sync) == ("gemini", {}, None)
    assert dict(rig.secrets.get("gemini")) == {}
    assert dict(rig.secrets.get("canvas")) == {"token": "fake-canvas-token-1234"}


async def test_disconnect_does_not_touch_the_event_store() -> None:
    rig = Rig()
    await rig.settings.connect("gemini", {"api_key": KEY})

    class Spy(InMemoryEventStore):
        deleted: list[str] = []  # noqa: RUF012

        def delete_source(self, source: str, *, user_id: str = "local") -> int:
            self.deleted.append(source)
            return super().delete_source(source, user_id=user_id)

    spy = Spy()
    sync = SyncService({"canvas": rig.canvas}, rig.secrets, spy, FakeClock(NOW))
    settings = SettingsService(
        {"canvas": rig.canvas}, rig.secrets, sync, {"gemini": rig.integration}
    )

    await settings.disconnect("gemini")

    assert spy.deleted == []


async def test_disconnect_with_the_store_down_returns_an_error_state() -> None:
    rig = Rig(secrets=UnavailableSecretStore())

    result = await rig.settings.disconnect("gemini")

    assert result.sync is not None
    assert result.sync.message == "secret store unavailable"
    assert rig.sync.state("gemini") is None


async def test_the_sync_service_never_learns_of_the_integration() -> None:
    rig = Rig()
    await rig.settings.connect("gemini", {"api_key": KEY})

    states = await rig.sync.sync_all()

    assert rig.sync.sources() == ["canvas"]
    assert [state.source for state in states] == ["canvas"]
    with pytest.raises(UnknownSourceError):
        await rig.sync.sync("gemini")


async def test_an_unknown_name_is_still_unknown() -> None:
    rig = Rig()

    with pytest.raises(UnknownSourceError):
        await rig.settings.connect("nope", {"api_key": KEY})
    with pytest.raises(UnknownSourceError):
        await rig.settings.disconnect("nope")


def test_one_name_cannot_be_both_a_source_and_an_integration() -> None:
    adapter = FakeAdapter("gemini")
    secrets = InMemorySecretStore()
    sync = SyncService({"gemini": adapter}, secrets, InMemoryEventStore(), FakeClock(NOW))

    with pytest.raises(ValueError, match="both a source and an integration"):
        SettingsService({"gemini": adapter}, secrets, sync, {"gemini": FakeIntegration()})
