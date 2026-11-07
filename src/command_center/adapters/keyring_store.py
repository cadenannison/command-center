"""SecretStore over the OS keychain. The only module that imports keyring."""

import json
import threading
from collections.abc import Callable, Mapping

import keyring
import keyring.errors
from pydantic import TypeAdapter, ValidationError

from command_center.core.schema import SecretStatus, secret_status

SERVICE = "command-center"
_BLOB = TypeAdapter(dict[str, str])
# One lock for every store in the process: set is read-modify-write on a shared blob, so two
# threads setting different keys of one source would otherwise lose an update. It does not
# protect against a second process (decision 0012).
_WRITE_LOCK = threading.Lock()


class SecretStoreError(Exception):
    """The OS keychain could not be used; the message says why and never contains a secret."""


class KeyringSecretStore:
    """Keeps one JSON blob (key -> value) per (user, source) as a single keychain entry."""

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:
        with _WRITE_LOCK:
            blob = dict(self._read(source, user_id))
            blob[key] = value
            self._write(source, user_id, blob)

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:
        return self._read(source, user_id)

    def status(self, source: str, *, user_id: str = "local") -> Mapping[str, SecretStatus]:
        return {key: secret_status(value) for key, value in self._read(source, user_id).items()}

    def delete(self, source: str, *, user_id: str = "local") -> None:
        username = _username(source, user_id)
        with _WRITE_LOCK:
            self._guarded(lambda: _delete_entry(username))

    def _read(self, source: str, user_id: str) -> dict[str, str]:
        username = _username(source, user_id)
        raw = self._guarded(lambda: keyring.get_password(SERVICE, username))
        if raw is None:
            return {}
        blob = _parse_blob(raw)
        if blob is None:
            msg = (
                f"Stored secret for source {source!r} is corrupt; delete the source and re-enter it"
            )
            raise SecretStoreError(msg)
        return blob

    def _write(self, source: str, user_id: str, blob: Mapping[str, str]) -> None:
        username = _username(source, user_id)
        self._guarded(lambda: keyring.set_password(SERVICE, username, json.dumps(blob)))

    @staticmethod
    def _guarded[T](operation: Callable[[], T]) -> T:
        try:
            return operation()
        except keyring.errors.NoKeyringError:
            msg = (
                "No OS keyring backend is available (macOS Keychain, Secret Service or Windows "
                "Credential Locker); secrets cannot be stored or read"
            )
        except keyring.errors.KeyringError as exc:
            msg = f"Keyring operation failed: {type(exc).__name__}"
        # Raised outside the except blocks so the backend's own message never chains onto ours.
        raise SecretStoreError(msg)


def _delete_entry(username: str) -> None:
    """Delete the entry; a missing one is not an error (backends signal it as a failed delete)."""
    try:
        keyring.delete_password(SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        if keyring.get_password(SERVICE, username) is not None:
            raise


def _parse_blob(raw: str) -> dict[str, str] | None:
    """Parse a stored blob; None if corrupt. pydantic's error quotes the input (secret material),
    so it is dropped here rather than chained onto ours."""
    try:
        return _BLOB.validate_json(raw)
    except ValidationError:
        return None


def _username(source: str, user_id: str) -> str:
    # JSON-encoded pair so ("a:b", "c") and ("a", "b:c") cannot collide.
    return json.dumps([user_id, source])
