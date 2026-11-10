"""Pure ledger types and functions: local tasks, patches, notes, history and mark overlay."""

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from builders import NAIVE, NOW, make_event
from command_center.core.ledger import (
    DONE_STATUS,
    LOCAL_SOURCE,
    MAX_LABEL,
    MAX_NOTE,
    MAX_TITLE,
    TASK_KIND,
    HistoryGroup,
    ItemMark,
    LedgerEntry,
    NoteInput,
    TaskInput,
    TaskPatch,
    apply_task_patch,
    group_history,
    group_history_range,
    is_local,
    local_task_event,
    overlay_marks,
)
from command_center.core.schema import Event, event_id

DUE = NOW + timedelta(days=2)


class SequentialIds:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


def test_constants_have_the_documented_values() -> None:
    assert (LOCAL_SOURCE, TASK_KIND, DONE_STATUS) == ("local", "task", "done")
    assert (MAX_TITLE, MAX_LABEL, MAX_NOTE) == (200, 80, 4000)


# TaskInput


def test_task_input_accepts_a_title_of_exactly_the_limit() -> None:
    assert len(TaskInput(title="a" * MAX_TITLE, due=DUE).title) == MAX_TITLE


def test_task_input_rejects_a_title_over_the_limit() -> None:
    with pytest.raises(ValidationError, match="title must be 1 to 200 characters"):
        TaskInput(title="a" * (MAX_TITLE + 1), due=DUE)


@pytest.mark.parametrize("title", ["", "   ", "\n\t "])
def test_task_input_rejects_a_blank_title(title: str) -> None:
    with pytest.raises(ValidationError, match="title must be 1 to 200 characters"):
        TaskInput(title=title, due=DUE)


def test_task_input_strips_the_title() -> None:
    assert TaskInput(title="  Read ch. 4 \n", due=DUE).title == "Read ch. 4"


def test_task_input_limit_counts_the_stripped_title() -> None:
    assert TaskInput(title="  " + "a" * MAX_TITLE + "  ", due=DUE).title == "a" * MAX_TITLE


def test_task_input_accepts_a_label_of_exactly_the_limit() -> None:
    assert TaskInput(title="t", due=DUE, label="b" * MAX_LABEL).label == "b" * MAX_LABEL


def test_task_input_rejects_a_label_over_the_limit() -> None:
    with pytest.raises(ValidationError, match="label must be at most 80 characters"):
        TaskInput(title="t", due=DUE, label="b" * (MAX_LABEL + 1))


@pytest.mark.parametrize("label", [None, "", "   "])
def test_task_input_blank_label_becomes_none(label: str | None) -> None:
    assert TaskInput(title="t", due=DUE, label=label).label is None


def test_task_input_strips_the_label() -> None:
    assert TaskInput(title="t", due=DUE, label=" CS 101 ").label == "CS 101"


def test_task_input_rejects_a_naive_due() -> None:
    with pytest.raises(ValidationError):
        TaskInput(title="t", due=NAIVE)


def test_task_input_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TaskInput.model_validate({"title": "t", "due": DUE, "source": "canvas"})


def test_task_input_is_frozen() -> None:
    task = TaskInput(title="t", due=DUE)

    with pytest.raises(ValidationError):
        task.title = "other"  # type: ignore[misc]


def test_task_input_error_never_contains_the_submitted_title() -> None:
    title = "fake-title-" + "x" * MAX_TITLE
    with pytest.raises(ValidationError) as caught:
        TaskInput(title=title, due=DUE)

    assert title not in str(caught.value)
    assert all(title not in str(error["msg"]) for error in caught.value.errors())


def test_task_input_label_error_never_contains_the_submitted_label() -> None:
    label = "fake-label-" + "z" * MAX_LABEL
    with pytest.raises(ValidationError) as caught:
        TaskInput(title="t", due=DUE, label=label)

    assert label not in str(caught.value)


@given(title=st.text(max_size=300), label=st.one_of(st.none(), st.text(max_size=120)))
def test_task_input_either_accepts_within_limits_or_rejects(title: str, label: str | None) -> None:
    title_ok = 1 <= len(title.strip()) <= MAX_TITLE
    label_ok = label is None or len(label.strip()) <= MAX_LABEL
    try:
        task = TaskInput(title=title, due=DUE, label=label)
    except ValidationError:
        assert not (title_ok and label_ok)
    else:
        assert title_ok
        assert label_ok
        assert task.label is None or task.label == task.label.strip() != ""


# TaskPatch


def test_task_patch_with_nothing_given_has_no_fields_set() -> None:
    assert TaskPatch().model_fields_set == set()


def test_task_patch_records_which_fields_were_given() -> None:
    patch = TaskPatch(title="New", label=None)

    assert patch.model_fields_set == {"title", "label"}


def test_task_patch_given_title_may_not_be_none() -> None:
    with pytest.raises(ValidationError, match="title must be 1 to 200 characters"):
        TaskPatch(title=None)


def test_task_patch_given_due_may_not_be_none() -> None:
    with pytest.raises(ValidationError, match="due cannot be cleared"):
        TaskPatch(due=None)


def test_task_patch_title_follows_the_task_rules() -> None:
    with pytest.raises(ValidationError, match="title must be 1 to 200 characters"):
        TaskPatch(title="a" * (MAX_TITLE + 1))
    assert TaskPatch(title="  New ").title == "New"


@pytest.mark.parametrize("label", [None, "", "  "])
def test_task_patch_given_blank_label_means_clear(label: str | None) -> None:
    patch = TaskPatch(label=label)

    assert patch.label is None
    assert "label" in patch.model_fields_set


def test_task_patch_label_over_the_limit_is_rejected() -> None:
    with pytest.raises(ValidationError, match="label must be at most 80 characters"):
        TaskPatch(label="b" * (MAX_LABEL + 1))


def test_task_patch_error_never_contains_the_submitted_title() -> None:
    title = "fake-title-" + "x" * MAX_TITLE
    with pytest.raises(ValidationError) as caught:
        TaskPatch(title=title)

    assert title not in str(caught.value)


def test_task_patch_read_from_json_keeps_absent_fields_unset() -> None:
    patch = TaskPatch.model_validate_json('{"label": null}')

    assert patch.model_fields_set == {"label"}


# NoteInput


def test_note_input_accepts_text_of_exactly_the_limit() -> None:
    assert len(NoteInput(text="n" * MAX_NOTE).text) == MAX_NOTE


def test_note_input_rejects_text_over_the_limit() -> None:
    with pytest.raises(ValidationError, match="note must be 1 to 4000 characters"):
        NoteInput(text="n" * (MAX_NOTE + 1))


@pytest.mark.parametrize("text", ["", "  ", "\n\n\t"])
def test_note_input_rejects_blank_text(text: str) -> None:
    with pytest.raises(ValidationError, match="note must be 1 to 4000 characters"):
        NoteInput(text=text)


def test_note_input_keeps_inner_and_leading_text_but_strips_trailing_whitespace() -> None:
    assert NoteInput(text="  line one\n\nline two  \n").text == "  line one\n\nline two"


def test_note_input_error_never_contains_the_submitted_text() -> None:
    text = "fake-note-" + "n" * MAX_NOTE
    with pytest.raises(ValidationError) as caught:
        NoteInput(text=text)

    assert text not in str(caught.value)


# local_task_event


def test_local_task_event_derives_its_id_from_the_id_source() -> None:
    event = local_task_event(TaskInput(title="Pay rent", due=DUE), SequentialIds(), NOW)

    assert event.id == event_id(LOCAL_SOURCE, "id-1")


def test_local_task_event_is_deterministic_with_a_fake_id_source() -> None:
    task = TaskInput(title="Pay rent", due=DUE)

    assert local_task_event(task, SequentialIds(), NOW) == local_task_event(
        task, SequentialIds(), NOW
    )


def test_local_task_event_uses_a_new_id_for_each_task() -> None:
    ids = SequentialIds()
    task = TaskInput(title="Pay rent", due=DUE)

    assert local_task_event(task, ids, NOW).id != local_task_event(task, ids, NOW).id


def test_local_task_event_fills_the_task_fields() -> None:
    event = local_task_event(TaskInput(title="Pay rent", due=DUE), SequentialIds(), NOW)

    assert (event.source, event.kind, event.title, event.due) == ("local", "task", "Pay rent", DUE)
    assert event.start is None
    assert event.end is None
    assert event.status is None
    assert event.urgency == 0
    assert event.fetched_at == NOW
    assert event.raw == {}


def test_local_task_event_stores_the_label_in_raw() -> None:
    task = TaskInput(title="Essay", due=DUE, label="ENG 200")

    assert local_task_event(task, SequentialIds(), NOW).raw == {"label": "ENG 200"}


def test_local_task_event_rejects_a_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        local_task_event(TaskInput(title="t", due=DUE), SequentialIds(), NAIVE)


def test_local_task_event_is_local() -> None:
    assert is_local(local_task_event(TaskInput(title="t", due=DUE), SequentialIds(), NOW))


# is_local


@pytest.mark.parametrize(
    ("source", "kind", "expected"),
    [
        ("local", "task", True),
        ("local", "event", False),
        ("canvas", "task", False),
        ("canvas", "assignment", False),
    ],
)
def test_is_local_needs_local_source_and_task_kind(
    source: str,
    kind: str,
    expected: bool,  # noqa: FBT001
) -> None:
    assert is_local(make_event(source=source, kind=kind)) is expected


# apply_task_patch


def _local(**overrides: object) -> Event:
    fields: dict[str, object] = {
        "source": "local",
        "kind": "task",
        "title": "Old",
        "due": DUE,
        "raw": {"label": "Old label", "keep": 1},
    }
    fields.update(overrides)
    return make_event(**fields)


def test_apply_task_patch_refuses_a_synced_item() -> None:
    with pytest.raises(ValueError, match="only local tasks can be changed"):
        apply_task_patch(make_event(kind="assignment"), TaskPatch(title="x"), NOW)


def test_apply_task_patch_refuses_a_local_non_task() -> None:
    with pytest.raises(ValueError, match="only local tasks can be changed"):
        apply_task_patch(make_event(source="local", kind="event"), TaskPatch(title="x"), NOW)


def test_apply_task_patch_changes_only_the_given_fields() -> None:
    later = NOW + timedelta(hours=3)

    patched = apply_task_patch(_local(), TaskPatch(title="New"), later)

    assert patched.title == "New"
    assert patched.due == DUE
    assert patched.raw == {"label": "Old label", "keep": 1}
    assert patched.fetched_at == later
    assert patched.id == "evt-1"


def test_apply_task_patch_changes_the_due_date() -> None:
    new_due = DUE + timedelta(days=1)

    assert apply_task_patch(_local(), TaskPatch(due=new_due), NOW).due == new_due


def test_apply_task_patch_sets_the_label_and_keeps_other_raw_keys() -> None:
    patched = apply_task_patch(_local(), TaskPatch(label="New label"), NOW)

    assert patched.raw == {"label": "New label", "keep": 1}


def test_apply_task_patch_clears_the_label_and_keeps_other_raw_keys() -> None:
    patched = apply_task_patch(_local(), TaskPatch(label=None), NOW)

    assert patched.raw == {"keep": 1}


def test_apply_task_patch_clearing_a_missing_label_is_fine() -> None:
    assert apply_task_patch(_local(raw={}), TaskPatch(label=""), NOW).raw == {}


def test_apply_task_patch_leaves_the_label_when_not_given() -> None:
    assert apply_task_patch(_local(), TaskPatch(), NOW).raw == {"label": "Old label", "keep": 1}


def test_apply_task_patch_does_not_change_its_input() -> None:
    original = _local()

    apply_task_patch(original, TaskPatch(title="New", label=None), NOW)

    assert original.title == "Old"
    assert original.raw == {"label": "Old label", "keep": 1}


def test_apply_task_patch_rejects_a_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_task_patch(_local(), TaskPatch(title="x"), NAIVE)


# group_history


def _entry(item_id: str, at: datetime, group: HistoryGroup) -> LedgerEntry:
    return LedgerEntry(
        item_id=item_id, source="canvas", kind="assignment", title="T", at=at, group=group
    )


def test_group_history_puts_each_entry_in_its_bucket() -> None:
    entries = [
        _entry("a", NOW, "done_by_you"),
        _entry("b", NOW, "done_by_source"),
        _entry("c", NOW, "gone"),
    ]

    day = group_history(date(2026, 11, 7), entries)

    assert [e.item_id for e in day.done_by_you] == ["a"]
    assert [e.item_id for e in day.done_by_source] == ["b"]
    assert [e.item_id for e in day.gone] == ["c"]
    assert day.day == date(2026, 11, 7)


def test_group_history_orders_each_bucket_by_time_then_id() -> None:
    entries = [
        _entry("z", NOW, "done_by_you"),
        _entry("b", NOW + timedelta(hours=1), "done_by_you"),
        _entry("a", NOW, "done_by_you"),
    ]

    day = group_history(date(2026, 11, 7), entries)

    assert [e.item_id for e in day.done_by_you] == ["a", "z", "b"]


def test_group_history_of_nothing_is_three_empty_buckets() -> None:
    day = group_history(date(2026, 11, 7), [])

    assert (day.done_by_you, day.done_by_source, day.gone) == ([], [], [])


@given(
    seeds=st.lists(
        st.tuples(
            st.text(alphabet="abc", min_size=1, max_size=2),
            st.integers(min_value=0, max_value=5),
            st.sampled_from(["done_by_you", "done_by_source", "gone"]),
        ),
        max_size=20,
    )
)
def test_group_history_keeps_every_entry_exactly_once_and_sorted(
    seeds: list[tuple[str, int, HistoryGroup]],
) -> None:
    entries = [_entry(i, NOW + timedelta(hours=h), g) for i, h, g in seeds]

    day = group_history(date(2026, 11, 7), entries)

    buckets = (day.done_by_you, day.done_by_source, day.gone)
    assert sum(len(b) for b in buckets) == len(entries)
    for bucket in buckets:
        keys = [(e.at, e.item_id) for e in bucket]
        assert keys == sorted(keys)


def test_group_history_does_not_change_its_input_order() -> None:
    entries = [_entry("b", NOW, "gone"), _entry("a", NOW, "gone")]

    group_history(date(2026, 11, 7), entries)

    assert [e.item_id for e in entries] == ["b", "a"]


def test_ledger_entry_rejects_unknown_group() -> None:
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate(
            {"item_id": "a", "source": "s", "kind": "k", "title": "t", "at": NOW, "group": "x"}
        )


def _reopened(item_id: str) -> LedgerEntry:
    return LedgerEntry(
        item_id=item_id,
        source="canvas",
        kind="assignment",
        title="T",
        at=NOW,
        group="done_by_source",
        reopened=True,
    )


def test_ledger_entry_reopened_defaults_to_false() -> None:
    assert _entry("a", NOW, "done_by_source").reopened is False


def test_ledger_entry_reopened_can_be_true_for_a_done_by_source_entry() -> None:
    entry = _reopened("a")

    assert entry.reopened is True
    assert entry.completed_by == "source"


def test_ledger_entry_reopened_appears_in_the_dump_and_json() -> None:
    entry = _reopened("a")

    assert entry.model_dump()["reopened"] is True
    assert '"reopened":true' in entry.model_dump_json()
    assert _entry("b", NOW, "gone").model_dump()["reopened"] is False


def test_group_history_passes_the_reopened_flag_through() -> None:
    reopened = _reopened("a")

    day = group_history(date(2026, 11, 7), [reopened, _entry("b", NOW, "done_by_source")])

    assert [(e.item_id, e.reopened) for e in day.done_by_source] == [("a", True), ("b", False)]


def test_group_history_range_keeps_the_reopened_flag_on_the_completion_day() -> None:
    reopened = _reopened("a")

    days = group_history_range([reopened], UTC)

    assert [(d.day, [e.reopened for e in d.done_by_source]) for d in days] == [(NOW.date(), [True])]


# overlay_marks


def _mark(**fields: object) -> ItemMark:
    base: dict[str, object] = {
        "item_id": "evt-1",
        "has_note": False,
        "note": None,
        "done_by": None,
        "done_at": None,
    }
    base.update(fields)
    return ItemMark.model_validate(base)


def test_overlay_marks_without_a_mark_returns_the_same_object() -> None:
    event = make_event(kind="assignment", due=DUE, urgency=70)

    assert overlay_marks(event, None) is event


def test_overlay_marks_with_nothing_to_overlay_returns_the_same_object() -> None:
    event = make_event(kind="assignment", due=DUE)

    assert overlay_marks(event, _mark()) is event


def test_overlay_marks_sets_has_note_when_the_mark_has_a_note() -> None:
    event = make_event(kind="assignment", due=DUE)

    result = overlay_marks(event, _mark(has_note=True, note="bring laptop"))

    assert result.has_note is True
    assert result.status == event.status


def test_overlay_marks_user_check_off_sets_done_status_and_clears_priority() -> None:
    event = make_event(kind="assignment", due=DUE, urgency=70)
    assert event.priority == 7

    result = overlay_marks(event, _mark(done_by="user", done_at=NOW))

    assert result.status == "done"
    assert result.priority is None
    assert result.has_note is False


def test_overlay_marks_source_completion_leaves_an_open_event_open() -> None:
    event = make_event(kind="assignment", due=DUE, urgency=70)

    result = overlay_marks(event, _mark(done_by="source", done_at=NOW))

    assert result.status == event.status
    assert result.status != "done"
    assert result.priority == 7


def test_overlay_marks_source_completion_keeps_a_done_event_done() -> None:
    event = make_event(kind="assignment", due=DUE, status="done")

    result = overlay_marks(event, _mark(done_by="source", done_at=NOW))

    assert result.status == "done"


def test_overlay_marks_user_check_off_keeps_a_done_event_done() -> None:
    event = make_event(kind="assignment", due=DUE, status="done")

    assert overlay_marks(event, _mark(done_by="user", done_at=NOW)).status == "done"


@pytest.mark.parametrize(
    ("done_by", "event_status", "expected"),
    [
        ("user", None, "done"),
        ("source", None, None),
        ("source", "done", "done"),
    ],
)
def test_overlay_marks_applies_the_note_flag_whoever_completed(
    done_by: str, event_status: str | None, expected: str | None
) -> None:
    event = make_event(kind="assignment", due=DUE, status=event_status)

    result = overlay_marks(event, _mark(has_note=True, note="n", done_by=done_by, done_at=NOW))

    assert result.has_note is True
    assert result.status == expected


def test_overlay_marks_source_completion_alone_returns_the_same_object() -> None:
    event = make_event(kind="assignment", due=DUE)

    assert overlay_marks(event, _mark(done_by="source", done_at=NOW)) is event


def test_overlay_marks_applies_note_and_done_together() -> None:
    event = make_event(kind="assignment", due=DUE)

    result = overlay_marks(event, _mark(has_note=True, note="n", done_by="user", done_at=NOW))

    assert (result.has_note, result.status) == (True, "done")


def test_overlay_marks_changes_no_other_field() -> None:
    event = make_event(
        kind="email", title="Hi", link="https://x.test", urgency=50, status="owed", raw={"a": 1}
    )

    result = overlay_marks(event, _mark(has_note=True, note="n", done_by="user", done_at=NOW))

    assert result.model_dump(exclude={"has_note", "status", "priority"}) == event.model_dump(
        exclude={"has_note", "status", "priority"}
    )


def test_overlay_marks_does_not_change_the_event_it_was_given() -> None:
    event = make_event(kind="assignment", due=DUE)

    overlay_marks(event, _mark(has_note=True, note="n", done_by="user", done_at=NOW))

    assert event.has_note is False
    assert event.status is None


def test_item_mark_requires_an_aware_done_at() -> None:
    with pytest.raises(ValidationError):
        _mark(done_by="user", done_at=NAIVE)


# Event schema


def test_event_accepts_the_task_kind() -> None:
    assert make_event(kind="task").kind == "task"


def test_event_has_note_defaults_to_false() -> None:
    assert make_event().has_note is False


def test_event_with_has_note_round_trips_through_a_dump() -> None:
    event = make_event(has_note=True)

    assert Event.model_validate(event.model_dump()) == event
    assert Event.model_validate(event.model_dump()).has_note is True


def test_event_dumped_before_has_note_existed_still_validates() -> None:
    old = make_event().model_dump(exclude={"has_note"})
    assert "has_note" not in old

    assert Event.model_validate(old).has_note is False


def test_event_json_round_trips_with_has_note() -> None:
    event = make_event(has_note=True, fetched_at=datetime(2026, 11, 7, 12, tzinfo=UTC))

    assert Event.model_validate_json(event.model_dump_json()) == event
