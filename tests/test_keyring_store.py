"""KeyringSecretStore against an in-test fake keyring backend; never the real keychain."""

import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import keyring
import keyring.backend
import keyring.backends.fail
import keyring.errors
import pytest

from command_center.adapters.keyring_store import SERVICE, KeyringSecretStore, SecretStoreError


class FakeKeyring(keyring.backend.KeyringBackend):
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


class YieldingKeyring(FakeKeyring):
    """Pauses after every read so concurrent writers overlap if nothing serialises them.

    The pause only widens the race window; the assertion does not depend on its length.
    """

    def get_password(self, service: str, username: str) -> str | None:
        value = super().get_password(service, username)
        threading.Event().wait(0.02)
        return value


class LockedKeyring(FakeKeyring):
    def get_password(self, service: str, username: str) -> str | None:
        message = f"locked while reading {service}/{username} fake-secret-value-123"
        raise keyring.errors.KeyringLocked(message)


@pytest.fixture(autouse=True)
def backend() -> Iterator[FakeKeyring]:
    original = keyring.get_keyring()
    fake = FakeKeyring()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(original)


@pytest.fixture
def store() -> KeyringSecretStore:
    return KeyringSecretStore()


def test_get_returns_empty_when_nothing_is_stored(store: KeyringSecretStore) -> None:
    assert store.get("caldav") == {}


def test_set_then_get_returns_every_key(store: KeyringSecretStore) -> None:
    store.set("caldav", "username", "me@example.com")
    store.set("caldav", "password", "fake-app-specific-password")
    assert store.get("caldav") == {
        "username": "me@example.com",
        "password": "fake-app-specific-password",
    }


def test_set_replaces_one_key_and_keeps_the_others(store: KeyringSecretStore) -> None:
    store.set("caldav", "username", "me")
    store.set("caldav", "password", "fake-old-password")
    store.set("caldav", "password", "fake-new-password")
    assert store.get("caldav") == {"username": "me", "password": "fake-new-password"}


def test_sources_are_independent(store: KeyringSecretStore) -> None:
    store.set("canvas", "token", "fake-canvas-token-1")
    store.set("gmail", "token", "fake-gmail-token-2")
    assert store.get("canvas") == {"token": "fake-canvas-token-1"}


def test_users_are_independent(store: KeyringSecretStore) -> None:
    store.set("canvas", "token", "fake-alice-token", user_id="alice")
    assert store.get("canvas") == {}


def test_user_and_source_that_concatenate_alike_do_not_collide(store: KeyringSecretStore) -> None:
    store.set("c", "token", "fake-first-value", user_id="a:b")
    store.set("b:c", "token", "fake-second-value", user_id="a")
    assert store.get("c", user_id="a:b") == {"token": "fake-first-value"}


def test_status_of_long_value_reveals_only_last_four(store: KeyringSecretStore) -> None:
    store.set("canvas", "token", "fake-abcdefgh1234")
    status = store.status("canvas")["token"]
    assert (status.set, status.last4) == (True, "1234")


def test_status_of_eight_character_value_reveals_last_four(store: KeyringSecretStore) -> None:
    store.set("canvas", "token", "fake-123")
    assert store.status("canvas")["token"].last4 == "-123"


def test_status_of_seven_character_value_hides_last_four(store: KeyringSecretStore) -> None:
    store.set("canvas", "token", "fake-12")
    status = store.status("canvas")["token"]
    assert (status.set, status.last4) == (True, None)


def test_status_is_per_key(store: KeyringSecretStore) -> None:
    store.set("caldav", "username", "me")
    store.set("caldav", "password", "fake-long-password")
    status = store.status("caldav")
    assert {key: s.last4 for key, s in status.items()} == {"username": None, "password": "word"}


def test_status_is_empty_when_nothing_is_stored(store: KeyringSecretStore) -> None:
    assert store.status("caldav") == {}


def test_status_never_contains_the_value(store: KeyringSecretStore) -> None:
    store.set("canvas", "token", "fake-super-secret-token-value")
    assert "super-secret" not in repr(store.status("canvas"))


def test_delete_removes_every_key_of_the_source(store: KeyringSecretStore) -> None:
    store.set("caldav", "username", "me")
    store.set("caldav", "password", "fake-long-password")
    store.delete("caldav")
    assert store.get("caldav") == {}


def test_delete_leaves_other_sources(store: KeyringSecretStore) -> None:
    store.set("caldav", "password", "fake-long-password")
    store.set("canvas", "token", "fake-canvas-token-1")
    store.delete("caldav")
    assert store.get("canvas") == {"token": "fake-canvas-token-1"}


def test_delete_when_nothing_is_stored_is_not_an_error(store: KeyringSecretStore) -> None:
    store.delete("caldav")


def test_one_keychain_entry_is_used_per_user_and_source(
    store: KeyringSecretStore, backend: FakeKeyring
) -> None:
    store.set("caldav", "username", "me")
    store.set("caldav", "password", "fake-long-password")
    ((service, _),) = backend.entries
    assert (service, len(backend.entries)) == (SERVICE, 1)


def test_corrupt_stored_blob_raises_without_echoing_it(
    store: KeyringSecretStore, backend: FakeKeyring
) -> None:
    store.set("canvas", "token", "fake-abcdefgh1234")
    ((entry,),) = [list(backend.entries)]
    backend.entries[entry] = json.dumps({"token": 12345678, "leak": "fake-hunter2-hunter2"})
    with pytest.raises(SecretStoreError, match="corrupt") as caught:
        store.get("canvas")
    assert "hunter2" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_blob_that_is_not_json_raises_corrupt_error(
    store: KeyringSecretStore, backend: FakeKeyring
) -> None:
    store.set("canvas", "token", "fake-abcdefgh1234")
    ((entry,),) = [list(backend.entries)]
    backend.entries[entry] = "not json {"
    with pytest.raises(SecretStoreError, match="corrupt"):
        store.status("canvas")


def test_missing_backend_raises_a_clear_error() -> None:
    original = keyring.get_keyring()
    keyring.set_keyring(keyring.backends.fail.Keyring())
    try:
        with pytest.raises(SecretStoreError, match="No OS keyring backend"):
            KeyringSecretStore().set("canvas", "token", "fake-abcdefgh1234")
    finally:
        keyring.set_keyring(original)


def test_missing_backend_error_applies_to_every_method() -> None:
    original = keyring.get_keyring()
    keyring.set_keyring(keyring.backends.fail.Keyring())
    store = KeyringSecretStore()
    try:
        for call in (lambda: store.get("a"), lambda: store.status("a"), lambda: store.delete("a")):
            with pytest.raises(SecretStoreError, match="No OS keyring backend"):
                call()
    finally:
        keyring.set_keyring(original)


def test_other_keyring_failures_name_the_class_but_not_the_message() -> None:
    original = keyring.get_keyring()
    keyring.set_keyring(LockedKeyring())
    try:
        with pytest.raises(SecretStoreError, match="KeyringLocked") as caught:
            KeyringSecretStore().get("canvas")
    finally:
        keyring.set_keyring(original)
    assert "fake-secret-value-123" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


class StuckEntryKeyring(FakeKeyring):
    def delete_password(self, service: str, username: str) -> None:  # noqa: ARG002
        raise keyring.errors.PasswordDeleteError


def test_failed_delete_of_an_entry_that_still_exists_raises() -> None:
    original = keyring.get_keyring()
    stuck = StuckEntryKeyring()
    keyring.set_keyring(stuck)
    try:
        KeyringSecretStore().set("canvas", "token", "fake-abcdefgh1234")
        with pytest.raises(SecretStoreError, match="PasswordDeleteError"):
            KeyringSecretStore().delete("canvas")
    finally:
        keyring.set_keyring(original)


def test_concurrent_sets_of_different_keys_lose_no_update() -> None:
    original = keyring.get_keyring()
    keyring.set_keyring(YieldingKeyring())
    try:
        workers = 8
        start_together = threading.Barrier(workers)

        def set_one(index: int) -> None:
            start_together.wait()
            KeyringSecretStore().set("caldav", f"key{index}", f"fake-value-{index}-abcdefgh")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in [pool.submit(set_one, i) for i in range(workers)]:
                future.result()
        stored = KeyringSecretStore().get("caldav")
    finally:
        keyring.set_keyring(original)
    assert stored == {f"key{i}": f"fake-value-{i}-abcdefgh" for i in range(workers)}


def test_deleting_a_corrupt_source_lets_its_keys_be_entered_again(
    store: KeyringSecretStore, backend: FakeKeyring
) -> None:
    store.set("canvas", "token", "fake-abcdefgh1234")
    ((entry,),) = [list(backend.entries)]
    backend.entries[entry] = "not json {"
    with pytest.raises(SecretStoreError, match="corrupt"):
        store.set("canvas", "token", "fake-replacement-1234")
    store.delete("canvas")
    store.set("canvas", "token", "fake-replacement-1234")
    assert store.get("canvas") == {"token": "fake-replacement-1234"}
