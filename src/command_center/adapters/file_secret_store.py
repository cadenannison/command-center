"""SecretStore over a 0600 JSON file, for containers where no OS keychain exists (decision 0073).

The file is `{user_id: {source: {key: value}}}` under a data directory that only this user may
enter (0700). Every write is read-modify-write under a lock file (`flock`, so separate processes
on one volume cannot lose each other's updates) and lands by atomic rename. Values are never
logged, returned by `status`, or put in an error message.
"""

import fcntl
import json
import os
import stat
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from command_center.core.errors import SecretStoreError
from command_center.core.schema import SecretStatus, secret_status

SECRETS_FILE = "secrets.json"
_FILE_MODE = 0o600
_DIR_MODE = 0o700
_BLOB = TypeAdapter(dict[str, dict[str, dict[str, str]]])
_THREAD_LOCK = threading.Lock()


class FileSecretStore:
    """Keeps every secret in one JSON file that only its owner can read."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / SECRETS_FILE
        self._lock_path = directory / f"{SECRETS_FILE}.lock"

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:
        with self._exclusive():
            blob = self._load()
            blob.setdefault(user_id, {}).setdefault(source, {})[key] = value
            self._save(blob)

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:
        return dict(self._load().get(user_id, {}).get(source, {}))

    def status(self, source: str, *, user_id: str = "local") -> Mapping[str, SecretStatus]:
        return {
            key: secret_status(value) for key, value in self.get(source, user_id=user_id).items()
        }

    def delete(self, source: str, *, user_id: str = "local") -> None:
        with self._exclusive():
            blob = self._load()
            if blob.get(user_id, {}).pop(source, None) is not None:
                self._save(blob)

    @contextmanager
    def _exclusive(self) -> Generator[None]:
        try:
            self._ensure_directory()
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, _FILE_MODE)
        except OSError as exc:
            msg = f"Secret file could not be locked: {type(exc).__name__}"
            raise SecretStoreError(msg) from None
        with _THREAD_LOCK:
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except OSError as exc:
                    msg = f"Secret file could not be locked: {type(exc).__name__}"
                    raise SecretStoreError(msg) from None
                yield
            finally:
                os.close(fd)  # closing releases the flock

    def _ensure_directory(self) -> None:
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        if stat.S_IMODE(directory.stat().st_mode) != _DIR_MODE:
            directory.chmod(_DIR_MODE)  # mkdir leaves an existing directory (a Docker volume) alone

    def _load(self) -> dict[str, dict[str, dict[str, str]]]:
        try:
            info = self._path.stat()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            msg = f"Secret file could not be read: {type(exc).__name__}"
            raise SecretStoreError(msg) from None
        if stat.S_IMODE(info.st_mode) & 0o077:
            msg = f"Secret file {self._path} is readable by others; run chmod 600 on it"
            raise SecretStoreError(msg)
        try:
            return _BLOB.validate_json(self._path.read_bytes())
        except OSError as exc:
            msg = f"Secret file could not be read: {type(exc).__name__}"
            raise SecretStoreError(msg) from None
        except ValidationError:
            # pydantic's error quotes the input, which is secret material: drop it.
            msg = "Secret file is corrupt; delete it and re-enter the credentials"
            raise SecretStoreError(msg) from None

    def _save(self, blob: dict[str, dict[str, dict[str, str]]]) -> None:
        temporary = self._path.with_name(f"{SECRETS_FILE}.{os.getpid()}.tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
            os.fchmod(fd, _FILE_MODE)  # a leftover temp file may carry looser bits
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(blob, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self._path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            msg = f"Secret file could not be written: {type(exc).__name__}"
            raise SecretStoreError(msg) from None
