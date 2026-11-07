"""Test doubles for service and api tests: a scripted SourceAdapter and failing/threaded stores."""

import asyncio
import threading
from collections.abc import Collection, Mapping, Sequence

from command_center.core.errors import SecretStoreError
from command_center.core.schema import Event, EventKind, SecretStatus, ValidationResult
from command_center.core.windows import TimeWindow
from fakes import InMemoryEventStore, InMemorySecretStore

KEYCHAIN_DETAIL = "Keyring operation failed: KeyringError for source 'canvas'"

type FetchStep = Exception | list[Event]


class FakeAdapter:
    """A SourceAdapter whose fetch results are scripted; the last step repeats forever."""

    def __init__(
        self,
        name: str = "canvas",
        *,
        script: Sequence[FetchStep] = (),
        validation: ValidationResult | None = None,
        validate_error: Exception | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self._name = name
        self._script = list(script) or [[]]
        self._validation = validation or ValidationResult(ok=True, message="Connected")
        self._validate_error = validate_error
        self._gate = gate
        self.fetches: list[tuple[Mapping[str, str], TimeWindow]] = []
        self.validations: list[Mapping[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    @property
    def name(self) -> str:
        return self._name

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        self.validations.append(dict(creds))
        if self._validate_error is not None:
            raise self._validate_error
        return self._validation

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        self.fetches.append((dict(creds), window))
        step = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._gate is not None:
                await self._gate.wait()
        finally:
            self.in_flight -= 1
        if isinstance(step, Exception):
            raise step
        return list(step)


class RecordingSleep:
    """Stands in for asyncio.sleep: records the requested delays and returns at once."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class UnavailableSecretStore:
    """A SecretStore whose every call fails like the keychain: the message names a source."""

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:  # noqa: ARG002
        raise SecretStoreError(KEYCHAIN_DETAIL)

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:  # noqa: ARG002
        raise SecretStoreError(KEYCHAIN_DETAIL)

    def status(self, source: str, *, user_id: str = "local") -> Mapping[str, SecretStatus]:  # noqa: ARG002
        raise SecretStoreError(KEYCHAIN_DETAIL)

    def delete(self, source: str, *, user_id: str = "local") -> None:  # noqa: ARG002
        raise SecretStoreError(KEYCHAIN_DETAIL)


class FailingSecondSetSecretStore(InMemorySecretStore):
    """A SecretStore whose second `set` fails, to leave a write half done."""

    def __init__(self) -> None:
        super().__init__()
        self._sets = 0

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:
        self._sets += 1
        if self._sets == 2:
            raise SecretStoreError(KEYCHAIN_DETAIL)
        super().set(source, key, value, user_id=user_id)


class ThreadRecordingEventStore(InMemoryEventStore):
    """An event store that notes which thread each call ran on."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: list[int] = []

    def upsert(self, events: Sequence[Event], *, user_id: str = "local") -> int:
        self.threads.append(threading.get_ident())
        return super().upsert(events, user_id=user_id)

    def query(
        self,
        window: TimeWindow,
        kinds: Collection[EventKind] | None = None,
        *,
        user_id: str = "local",
    ) -> list[Event]:
        self.threads.append(threading.get_ident())
        return super().query(window, kinds, user_id=user_id)


class ThreadRecordingSecretStore(InMemorySecretStore):
    """A secret store that notes which thread each call ran on."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: list[int] = []

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:
        self.threads.append(threading.get_ident())
        return super().get(source, user_id=user_id)
