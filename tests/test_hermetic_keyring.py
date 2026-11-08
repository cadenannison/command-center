"""The suite never reaches the OS keychain: an in-memory backend is installed and then removed."""

import keyring
import pytest

from command_center.adapters.keyring_store import KeyringSecretStore
from keyring_support import InMemoryKeyring, in_memory_keyring


class SentinelKeyring(InMemoryKeyring):
    """A distinct backend to stand in for the real one when checking what is restored."""


def raise_inside_the_context() -> None:
    with in_memory_keyring():
        msg = "boom"
        raise RuntimeError(msg)


def test_every_test_runs_against_an_in_memory_keyring(keyring_backend: InMemoryKeyring) -> None:
    assert keyring.get_keyring() is keyring_backend


def test_the_secret_store_writes_only_to_the_in_memory_backend(
    keyring_backend: InMemoryKeyring,
) -> None:
    KeyringSecretStore().set("canvas", "token", "fake-canvas-token-ABCD1234")

    assert len(keyring_backend.entries) == 1


def test_each_test_starts_with_an_empty_keyring(keyring_backend: InMemoryKeyring) -> None:
    assert keyring_backend.entries == {}


def test_the_previous_backend_is_restored_on_exit() -> None:
    sentinel = SentinelKeyring()
    with in_memory_keyring():
        keyring.set_keyring(sentinel)
        with in_memory_keyring():
            assert isinstance(keyring.get_keyring(), InMemoryKeyring)
        assert keyring.get_keyring() is sentinel


def test_the_previous_backend_is_restored_when_the_body_raises() -> None:
    sentinel = SentinelKeyring()
    with in_memory_keyring():
        keyring.set_keyring(sentinel)
        with pytest.raises(RuntimeError):
            raise_inside_the_context()
        assert keyring.get_keyring() is sentinel
