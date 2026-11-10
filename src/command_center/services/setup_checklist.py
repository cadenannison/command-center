"""The setup checklist of the settings page: each source's state and how long ago it last synced."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from command_center.services.models import SourceSettings, SyncStatus

SetupState = Literal["not_connected", "connected", "needs_attention"]


class SetupItem(BaseModel):
    """One line of the checklist. It carries no credential and no value."""

    model_config = ConfigDict(frozen=True)

    source: str
    state: SetupState
    sync_status: SyncStatus | None
    message: str
    last_sync_at: AwareDatetime | None
    # Seconds between last_sync_at and now; None when either is unknown (no sync yet, no clock).
    seconds_ago: int | None


def build_checklist(items: Sequence[SourceSettings], now: datetime | None) -> list[SetupItem]:
    """One SetupItem per source, in order.

    A source needs attention when its last sync asked for a reconnect or failed, which includes an
    unverified save (decision 0101). It is connected when it holds a stored key or a sync state
    that is not a failure; otherwise it is not connected.
    """
    return [_item(item, now) for item in items]


def _item(item: SourceSettings, now: datetime | None) -> SetupItem:
    sync = item.sync
    if sync is not None and sync.status in {"reconnect", "error"}:
        state: SetupState = "needs_attention"
    elif sync is not None or any(key.set for key in item.keys.values()):
        state = "connected"
    else:
        state = "not_connected"
    seconds = None if sync is None or now is None else max(0, int((now - sync.at).total_seconds()))
    return SetupItem(
        source=item.source,
        state=state,
        sync_status=None if sync is None else sync.status,
        message="" if sync is None else sync.message,
        last_sync_at=None if sync is None else sync.at,
        seconds_ago=seconds,
    )
