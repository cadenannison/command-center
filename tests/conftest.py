"""Suite-wide fixtures."""

from collections.abc import Iterator

import pytest

from keyring_support import InMemoryKeyring, in_memory_keyring


@pytest.fixture(autouse=True)
def keyring_backend() -> Iterator[InMemoryKeyring]:
    """Every test gets an empty in-memory keyring, so none touches the OS keychain (0055).

    Autouse because the real container builds `KeyringSecretStore`, and a test that forgot to opt
    in would read the developer's real keychain and depend on what earlier runs left there.
    """
    with in_memory_keyring() as backend:
        yield backend
