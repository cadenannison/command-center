"""FileSecretStore: the SecretStore contract over a 0600 file, and what it refuses to do."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from command_center.adapters.file_secret_store import SECRETS_FILE, FileSecretStore
from command_center.adapters.secret_backend import build_secret_store
from command_center.core.errors import SecretStoreError

SECRET = "fake-canvas-token-12345678"  # noqa: S105


@pytest.fixture
def store(tmp_path: Path) -> FileSecretStore:
    return FileSecretStore(tmp_path / "data")


def test_a_missing_file_reads_as_no_secret(store: FileSecretStore) -> None:
    assert dict(store.get("canvas")) == {}
    assert dict(store.status("canvas")) == {}


def test_set_then_get_returns_every_key(store: FileSecretStore) -> None:
    store.set("canvas", "token", SECRET)
    store.set("canvas", "base_url", "https://canvas.example.edu")
    assert dict(store.get("canvas")) == {"token": SECRET, "base_url": "https://canvas.example.edu"}


def test_status_shows_set_and_the_last_four_of_a_long_value_only(store: FileSecretStore) -> None:
    store.set("canvas", "token", SECRET)
    store.set("canvas", "short", "abc")
    status = store.status("canvas")
    assert (status["token"].set, status["token"].last4) == (True, "5678")
    assert status["short"].last4 is None
    assert SECRET not in repr(status)


def test_delete_removes_every_key_and_a_missing_source_is_not_an_error(
    store: FileSecretStore,
) -> None:
    store.set("canvas", "token", SECRET)
    store.set("gmail", "refresh_token", "fake-refresh-0000")
    store.delete("canvas")
    store.delete("canvas")
    assert dict(store.get("canvas")) == {}
    assert dict(store.get("gmail")) == {"refresh_token": "fake-refresh-0000"}


def test_secrets_are_per_user(store: FileSecretStore) -> None:
    store.set("canvas", "token", SECRET)
    assert dict(store.get("canvas", user_id="other")) == {}


def test_the_file_is_owner_only_and_so_is_its_directory(
    store: FileSecretStore, tmp_path: Path
) -> None:
    store.set("canvas", "token", SECRET)
    path = tmp_path / "data" / SECRETS_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_second_store_on_the_same_directory_sees_the_values(
    store: FileSecretStore, tmp_path: Path
) -> None:
    store.set("canvas", "token", SECRET)
    assert dict(FileSecretStore(tmp_path / "data").get("canvas")) == {"token": SECRET}


def test_no_temporary_file_is_left_behind(store: FileSecretStore, tmp_path: Path) -> None:
    store.set("canvas", "token", SECRET)
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == [
        SECRETS_FILE,
        f"{SECRETS_FILE}.lock",
    ]


def test_a_file_readable_by_others_is_refused_without_echoing_its_contents(
    store: FileSecretStore, tmp_path: Path
) -> None:
    store.set("canvas", "token", SECRET)
    (tmp_path / "data" / SECRETS_FILE).chmod(0o644)
    with pytest.raises(SecretStoreError) as error:
        store.get("canvas")
    assert SECRET not in str(error.value)
    assert "chmod 600" in str(error.value)


def test_a_corrupt_file_raises_a_secret_store_error_that_does_not_quote_it(
    store: FileSecretStore, tmp_path: Path
) -> None:
    path = tmp_path / "data" / SECRETS_FILE
    path.parent.mkdir()
    path.write_text(json.dumps({"local": {"canvas": {"token": 5}}}) + SECRET)
    path.chmod(0o600)
    with pytest.raises(SecretStoreError) as error:
        store.get("canvas")
    assert SECRET not in str(error.value)
    assert error.value.__cause__ is None


def test_concurrent_sets_of_different_keys_do_not_lose_an_update(store: FileSecretStore) -> None:
    def write(n: int) -> None:
        store.set("canvas", f"k{n}", f"v{n}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))
    assert dict(store.get("canvas")) == {f"k{n}": f"v{n}" for n in range(24)}


def test_an_unwritable_directory_is_a_secret_store_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(SecretStoreError):
        FileSecretStore(blocker / "data").set("canvas", "token", SECRET)
    assert os.path.isfile(blocker)  # noqa: PTH113


def test_the_backend_setting_picks_the_store(tmp_path: Path) -> None:
    assert isinstance(build_secret_store("file", tmp_path), FileSecretStore)
    assert not isinstance(build_secret_store("keyring", tmp_path), FileSecretStore)


def test_an_existing_loose_data_directory_is_tightened_to_owner_only(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)  # mkdir's mode is masked by the umask
    FileSecretStore(directory).set("canvas", "token", SECRET)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
