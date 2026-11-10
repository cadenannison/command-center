"""What a row needs to draw its item controls: check-off, note editor, task editor. Pure."""

from dataclasses import dataclass
from datetime import date, tzinfo

from command_center.core.ledger import ItemMark, is_local
from command_center.core.schema import Event

DONE = "done"
# Where a row sits on a page. Each copy of an item has its own element id, `row-<ctx>-<item id>`.
CONTEXTS = ("agenda", "attention", "week", "deadline")


@dataclass(frozen=True)
class TaskFields:
    """A local task as the edit form shows it: the due time in the settings timezone."""

    title: str
    due_date: str
    due_time: str
    label: str


@dataclass(frozen=True)
class ItemControls:
    """The controls of one row. `day` and `dated` say how the row's time was labelled, so the
    server can draw the same row again after a change."""

    item_id: str
    ctx: str
    day: str
    dated: bool
    done: bool
    can_undo: bool
    has_note: bool
    note: str
    task: TaskFields | None

    @property
    def row_id(self) -> str:
        """The element id of this row."""
        return f"row-{self.ctx}-{self.item_id}"

    @property
    def query(self) -> str:
        """The query string that lets a request redraw this row; every part is server-made."""
        day = f"&day={self.day}" if self.day else ""
        return f"ctx={self.ctx}{day}&dated={int(self.dated)}"


@dataclass(frozen=True)
class NewTaskForm:
    """The New task panel: what is typed (so an error keeps it) and the message, if any."""

    due_date: str
    title: str = ""
    due_time: str = ""
    label: str = ""
    error: str = ""


def task_fields(event: Event, tz: tzinfo) -> TaskFields | None:
    """The edit form values for a local task, None for any other item."""
    if not is_local(event):
        return None
    due = event.due.astimezone(tz) if event.due is not None else None
    label = event.raw.get("label")
    return TaskFields(
        title=event.title,
        due_date="" if due is None else due.date().isoformat(),
        due_time="" if due is None else f"{due:%H:%M}",
        label=label if isinstance(label, str) else "",
    )


def item_controls(  # noqa: PLR0913  (one value per thing the row shows)
    event: Event,
    mark: ItemMark | None,
    tz: tzinfo,
    *,
    ctx: str,
    day: date | None,
    dated: bool,
) -> ItemControls:
    """The controls for event, given its ledger mark (None when it has no note or check-off)."""
    return ItemControls(
        item_id=event.id,
        ctx=ctx,
        day="" if day is None else day.isoformat(),
        dated=dated,
        done=event.status == DONE,
        can_undo=mark is not None and mark.done_by == "user",
        has_note=event.has_note,
        note="" if mark is None or mark.note is None else mark.note,
        task=task_fields(event, tz),
    )


def needs_mark(event: Event) -> bool:
    """Whether the page must read the ledger for this event: it has a note or is done."""
    return event.has_note or event.status == DONE
