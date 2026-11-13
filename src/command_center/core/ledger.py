"""The item ledger's pure parts: local tasks, notes, history and marks laid over events."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, tzinfo
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, field_validator
from pydantic_core import PydanticCustomError

from command_center.core.schema import Event, event_id

if TYPE_CHECKING:
    from command_center.core.ports import IdSource

LOCAL_SOURCE = "local"
TASK_KIND = "task"
DONE_STATUS = "done"
MAX_TITLE = 200
MAX_LABEL = 80
MAX_NOTE = 4000

DoneBy = Literal["user", "source"]
HistoryGroup = Literal["done_by_you", "done_by_source", "gone", "dismissed"]
Outcome = Literal["done", "dismissed", "gone"]

# Fixed texts: a validation error must say what failed without echoing the submitted value.
_INPUT = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


# Fixed texts: a validation error never echoes what was typed (decision 0023).
_TITLE_LENGTH = "title_length"
_LABEL_LENGTH = "label_length"
_DUE_REQUIRED = "due_required"
_NOTE_LENGTH = "note_length"
_TITLE_MSG = "title must be 1 to 200 characters"
_LABEL_MSG = "label must be at most 80 characters"
_DUE_MSG = "due cannot be cleared"
_NOTE_MSG = "note must be 1 to 4000 characters"


def _clean_title(value: str | None) -> str:
    title = (value or "").strip()
    if not 1 <= len(title) <= MAX_TITLE:
        raise PydanticCustomError(_TITLE_LENGTH, _TITLE_MSG)
    return title


def _clean_label(value: str | None) -> str | None:
    label = (value or "").strip()
    if len(label) > MAX_LABEL:
        raise PydanticCustomError(_LABEL_LENGTH, _LABEL_MSG)
    return label or None


class TaskInput(BaseModel):
    """What the user types to make a local task."""

    model_config = _INPUT

    title: str
    due: AwareDatetime
    label: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _clean_title(value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        return _clean_label(value)


class TaskPatch(BaseModel):
    """A partial change to a local task; `model_fields_set` says which fields were given."""

    model_config = _INPUT

    title: str | None = None
    due: AwareDatetime | None = None
    label: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str:
        return _clean_title(value)

    @field_validator("due")
    @classmethod
    def _due(cls, value: datetime | None) -> datetime:
        if value is None:
            raise PydanticCustomError(_DUE_REQUIRED, _DUE_MSG)
        return value

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        return _clean_label(value)


class NoteInput(BaseModel):
    """A note as written; trailing whitespace is dropped, nothing else is changed."""

    model_config = _INPUT

    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        text = value.rstrip()
        if not text.strip() or len(text) > MAX_NOTE:
            raise PydanticCustomError(_NOTE_LENGTH, _NOTE_MSG)
        return text


class ItemMark(BaseModel):
    """What the ledger holds about one item: a note and/or who checked it off."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    has_note: bool
    note: str | None
    done_by: DoneBy | None
    done_at: AwareDatetime | None
    dismissed_at: AwareDatetime | None = None
    snoozed_until: AwareDatetime | None = None


class LedgerEntry(BaseModel):
    """One line of history: an item that was done or that vanished from its source."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    source: str
    kind: str
    title: str
    at: AwareDatetime
    group: HistoryGroup
    note: str | None = None
    link: str | None = None
    reopened: bool = False
    """True if the source completed the item, then reported it open again (done_by_source only)."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def completed_by(self) -> DoneBy | None:
        """Who finished the item: "user", "source", or None when it only vanished. Not stored."""
        if self.group == "done_by_you":
            return "user"
        if self.group == "done_by_source":
            return "source"
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def outcome(self) -> Outcome:
        """How the item left the lists: "done", "dismissed" or "gone". Not stored."""
        if self.group == "dismissed":
            return "dismissed"
        return "gone" if self.group == "gone" else "done"


class HistoryDay(BaseModel):
    """One day of history, split by how an item left the agenda."""

    model_config = ConfigDict(frozen=True)

    day: date
    done_by_you: list[LedgerEntry] = Field(default_factory=list[LedgerEntry])
    done_by_source: list[LedgerEntry] = Field(default_factory=list[LedgerEntry])
    gone: list[LedgerEntry] = Field(default_factory=list[LedgerEntry])
    dismissed: list[LedgerEntry] = Field(default_factory=list[LedgerEntry])


def _require_aware(now: datetime) -> None:
    if now.utcoffset() is None:
        msg = "a timezone-aware now is required"
        raise ValueError(msg)


def is_local(event: Event) -> bool:
    """True for a task the user made here; only these can be changed or deleted."""
    return event.source == LOCAL_SOURCE and event.kind == TASK_KIND


def local_task_event(task: TaskInput, ids: "IdSource", now: datetime) -> Event:
    """Build the stored event for a new local task; its urgency is rescored when read."""
    _require_aware(now)
    return Event(
        id=event_id(LOCAL_SOURCE, ids.new_id()),
        source=LOCAL_SOURCE,
        kind=TASK_KIND,
        title=task.title,
        due=task.due,
        raw={} if task.label is None else {"label": task.label},
        fetched_at=now,
    )


def apply_task_patch(event: Event, patch: TaskPatch, now: datetime) -> Event:
    """Return event with the fields the patch gave; a label of None removes it."""
    if not is_local(event):
        msg = "only local tasks can be changed"
        raise ValueError(msg)
    _require_aware(now)
    changes: dict[str, object] = {"fetched_at": now}
    given = patch.model_fields_set
    if "title" in given and patch.title is not None:
        changes["title"] = patch.title
    if "due" in given and patch.due is not None:
        changes["due"] = patch.due
    if "label" in given:
        raw = {key: value for key, value in event.raw.items() if key != "label"}
        if patch.label is not None:
            raw["label"] = patch.label
        changes["raw"] = raw
    return event.model_copy(update=changes)


def group_history(day: date, entries: Sequence[LedgerEntry]) -> HistoryDay:
    """Bucket entries by group, each bucket ordered by (at as a UTC instant, item_id)."""
    ordered = sorted(entries, key=lambda entry: (entry.at.astimezone(UTC), entry.item_id))
    return HistoryDay(
        day=day,
        done_by_you=[entry for entry in ordered if entry.group == "done_by_you"],
        done_by_source=[entry for entry in ordered if entry.group == "done_by_source"],
        gone=[entry for entry in ordered if entry.group == "gone"],
        dismissed=[entry for entry in ordered if entry.group == "dismissed"],
    )


def group_history_range(entries: Sequence[LedgerEntry], tz: tzinfo) -> list[HistoryDay]:
    """One HistoryDay per local day in tz that has an entry, ascending by day."""
    by_day: dict[date, list[LedgerEntry]] = {}
    for entry in entries:
        by_day.setdefault(entry.at.astimezone(tz).date(), []).append(entry)
    return [group_history(day, by_day[day]) for day in sorted(by_day)]


def overlay_marks(event: Event, mark: ItemMark | None, now: datetime | None = None) -> Event:
    """Show the ledger on event: has_note, status done for a user check-off, dismissal, snooze.

    A source completion never forces the status; the event's own status is the source's word.
    A snooze is shown only when `now` is given and the snooze has not run out.
    """
    if mark is None:
        return event
    changes: dict[str, object] = {}
    if mark.has_note and not event.has_note:
        changes["has_note"] = True
    if mark.done_by == "user" and event.status != DONE_STATUS:
        changes["status"] = DONE_STATUS
    if mark.dismissed_at is not None:
        changes["dismissed_at"] = mark.dismissed_at
    if now is not None and is_snoozed(mark.snoozed_until, now):
        changes["snoozed_until"] = mark.snoozed_until
    return event.model_copy(update=changes) if changes else event


def is_snoozed(until: datetime | None, now: datetime) -> bool:
    """True while the snooze holds: it ends at `until`, which is the first instant it is back."""
    return until is not None and until.astimezone(UTC) > now.astimezone(UTC)


def is_hidden(event: Event, now: datetime) -> bool:
    """True for an item the lists leave out: dismissed, or snoozed and not yet back."""
    return event.dismissed_at is not None or is_snoozed(event.snoozed_until, now)
