"""The last sync result of one source: what the settings view shows and workers record."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

SyncStatus = Literal["syncing", "ok", "reconnect", "error"]


class SyncState(BaseModel):
    """The last sync result of one source."""

    model_config = ConfigDict(frozen=True)

    source: str
    status: SyncStatus
    message: str
    at: AwareDatetime
