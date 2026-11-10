"""View model of the setup checklist at the top of the settings page."""

from collections.abc import Sequence
from dataclasses import dataclass

from command_center.services.setup_checklist import SetupItem
from command_center.web.sources import form_for

_STATE_LABELS = {
    "not_connected": "Not connected",
    "connected": "Connected",
    "needs_attention": "Needs attention",
}
_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR


def format_age(seconds: int) -> str:
    """How long ago, in the largest whole unit: "just now", "3 min ago", "2 h ago", "4 d ago"."""
    if seconds < _MINUTE:
        return "just now"
    if seconds < _HOUR:
        return f"{seconds // _MINUTE} min ago"
    if seconds < _DAY:
        return f"{seconds // _HOUR} h ago"
    return f"{seconds // _DAY} d ago"


@dataclass(frozen=True)
class ChecklistRow:
    """One source of the checklist."""

    source: str
    label: str
    state: str
    state_label: str
    when: str


def _when(item: SetupItem) -> str:
    if item.sync_status == "syncing":
        return "syncing now"
    if item.seconds_ago is None:
        return ""
    prefix = "last sync" if item.sync_status == "ok" else "last attempt"
    return f"{prefix} {format_age(item.seconds_ago)}"


def checklist_rows(items: Sequence[SetupItem]) -> list[ChecklistRow]:
    """One row per source: its state and when it last synced."""
    return [
        ChecklistRow(
            source=item.source,
            label=form_for(item.source).label,
            state=item.state,
            state_label=_STATE_LABELS[item.state],
            when=_when(item),
        )
        for item in items
    ]
