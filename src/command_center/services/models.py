"""Result types the services return. None of them can carry a credential value."""

from pydantic import BaseModel, ConfigDict

from command_center.core.schema import SecretStatus
from command_center.core.sync_state import SyncState, SyncStatus

__all__ = ["ConnectResult", "SourceSettings", "SyncState", "SyncStatus"]


class SourceSettings(BaseModel):
    """What the settings API may reveal about one source: per-key status plus its sync state."""

    model_config = ConfigDict(frozen=True)

    source: str
    keys: dict[str, SecretStatus]
    sync: SyncState | None = None


class ConnectResult(BaseModel):
    """Outcome of connecting a source.

    When `ok` is false nothing was stored, except if the secret store failed part-way through
    writing the keys: then the keys written before the failure stay stored.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    ok: bool
    message: str
    sync: SyncState | None = None
