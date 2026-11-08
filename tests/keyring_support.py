"""An in-memory keyring backend, so no test reads or writes the OS keychain."""

from collections.abc import Generator
from contextlib import contextmanager

import keyring
import keyring.backend
import keyring.errors


class InMemoryKeyring(keyring.backend.KeyringBackend):
    """Keeps entries in a dict. `priority` only matters to keyring's own backend search."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.entries:
            raise keyring.errors.PasswordDeleteError
        del self.entries[(service, username)]


@contextmanager
def in_memory_keyring() -> Generator[InMemoryKeyring]:
    """Install a fresh InMemoryKeyring; put the previous backend back on exit, even on error."""
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)
