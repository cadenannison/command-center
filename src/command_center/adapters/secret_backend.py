"""Chooses the SecretStore: the OS keychain (default) or a 0600 file (containers)."""

from pathlib import Path
from typing import Literal

from command_center.adapters.file_secret_store import FileSecretStore
from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.core.ports import SecretStore

type SecretBackend = Literal["keyring", "file"]


def build_secret_store(backend: SecretBackend, data_dir: Path) -> SecretStore:
    """The store for `backend`; the file backend keeps its file under `data_dir`."""
    if backend == "file":
        return FileSecretStore(data_dir)
    return KeyringSecretStore()
