"""Result types the services return. None of them can carry a credential value."""

from pydantic import BaseModel, ConfigDict, Field

from command_center.core.schema import SecretStatus
from command_center.core.sync_state import SyncState, SyncStatus

__all__ = ["ConnectResult", "SourceSettings", "SyncState", "SyncStatus"]


class SourceSettings(BaseModel):
    """What the settings API may reveal about one source: per-key status plus its sync state.

    `values` holds the stored value of each non-secret key (a Canvas URL, an Apple ID, a
    coordinate; see `credential_fields`). A secret key never appears in it, only in `keys` as
    set + last4 (decision 0100).
    """

    model_config = ConfigDict(frozen=True)

    source: str
    keys: dict[str, SecretStatus]
    sync: SyncState | None = None
    values: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Stored value of each set non-secret key. Always empty unless the request is "
            "loopback: a paired phone never receives it (decision 0106)."
        ),
    )


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
    # True only when the check failed with a transient (network) error: saving the typed values
    # unverified is then a sensible choice. Never for a rejected credential (decision 0101).
    can_save_unverified: bool = False
