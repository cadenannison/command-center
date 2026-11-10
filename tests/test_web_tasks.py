"""New task, edit and delete on the pages: local ledger items with due-based priority."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from builders import NOW
from command_center.core.ledger import MAX_LABEL, MAX_TITLE
from command_center.core.windows import TimeWindow
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine
from web_items_support import HEADERS, TODAY, ItemRig, make_item_rig, row_of, section

FORM = {"title": "Read chapter 4", "due_date": TODAY, "due_time": "15:00", "label": "BIO 101"}


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> ItemRig:
    return make_item_rig(ledger)


def create(rig: ItemRig, **changes: str) -> str:
    """Create a task through the form and return its id."""
    response = rig.client.post("/tasks", data={**FORM, **changes}, headers=HEADERS)
    assert response.status_code == 200
    assert "hx-redirect" in response.headers
    (task,) = [e for e in rig.ledger.events.query(everything()) if e.source == "local"]
    return task.id


def everything() -> TimeWindow:
    return TimeWindow(start=NOW - timedelta(days=60), end=NOW + timedelta(days=60))


def error_text(html: str) -> str:
    start = html.index('role="alert">') + len('role="alert">')
    return html[start : html.index("</p>", start)]


# ---- create -----------------------------------------------------------------------------------


def test_the_new_task_panel_is_on_today_week_and_month_prefilled_with_the_shown_day(
    rig: ItemRig,
) -> None:
    for path in ("/", "/week", "/month"):
        html = rig.page(path)
        assert "<summary>New task</summary>" in html
        assert 'name="due_date" type="date" value="2026-11-07"' in html
    assert 'value="2026-11-09"' in rig.page("/?date=2026-11-09")


def test_a_valid_form_creates_a_local_task_and_sends_the_browser_to_its_day(rig: ItemRig) -> None:
    response = rig.client.post("/tasks", data=FORM, headers=HEADERS)

    assert response.status_code == 200
    assert response.headers["hx-redirect"] == f"/?date={TODAY}"
    (task,) = [e for e in rig.ledger.events.query(everything()) if e.source == "local"]
    assert (task.kind, task.title, task.raw) == ("task", "Read chapter 4", {"label": "BIO 101"})


def test_the_due_time_is_read_in_the_settings_timezone(rig: ItemRig) -> None:
    create(rig)

    (task,) = [e for e in rig.ledger.events.query(everything()) if e.source == "local"]

    assert task.due == datetime(2026, 11, 7, 22, 0, tzinfo=UTC)  # 15:00 in Denver, UTC-7


def test_a_task_due_on_another_day_redirects_to_that_day(rig: ItemRig) -> None:
    response = rig.client.post(
        "/tasks", data={**FORM, "due_date": "2026-11-12", "due_time": "23:30"}, headers=HEADERS
    )

    assert response.headers["hx-redirect"] == "/?date=2026-11-12"


def test_the_new_task_is_in_the_agenda_with_a_due_based_priority_and_a_reason(
    rig: ItemRig,
) -> None:
    task_id = create(rig)

    row = row_of(rig.page(), task_id, "agenda")

    assert "Due 15:00" in row
    assert 'title="Priority 9 of 10"' in row  # due in 10 hours
    assert 'title="Due in 10 hours, not done"' in row
    assert "BIO 101" in row
    assert row_of(rig.page(), task_id, "attention")


def test_a_task_without_a_label_shows_no_label_chip(rig: ItemRig) -> None:
    task_id = create(rig, label="")

    assert "chip-label" not in row_of(rig.page(), task_id, "agenda")


def test_a_task_title_and_label_are_escaped_everywhere(rig: ItemRig) -> None:
    task_id = create(rig, title="<script>x()</script>", label='"><img src=x>')

    for path, ctx in (("/", "agenda"), ("/week", "week"), ("/month", "deadline")):
        html = rig.page(path)
        row = row_of(html, task_id, ctx)
        assert "<script>x()" not in html
        assert "<img src=x>" not in html
        assert "&lt;script&gt;x()&lt;/script&gt;" in row


def test_the_longest_title_and_label_are_accepted(rig: ItemRig) -> None:
    create(rig, title="t" * MAX_TITLE, label="l" * MAX_LABEL)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"title": ""}, "Title must be 1 to 200 characters."),
        ({"title": "   "}, "Title must be 1 to 200 characters."),
        ({"title": "t" * (MAX_TITLE + 1)}, "Title must be 1 to 200 characters."),
        ({"label": "l" * (MAX_LABEL + 1)}, "Label must be at most 80 characters."),
        ({"due_date": ""}, "Enter a due date and a due time."),
        ({"due_time": ""}, "Enter a due date and a due time."),
        ({"due_date": "2026-13-45"}, "The due date or time is not valid."),
        ({"due_date": "next week"}, "The due date or time is not valid."),
        ({"due_time": "25:99"}, "The due date or time is not valid."),
    ],
)
def test_a_bad_form_stores_nothing_and_comes_back_with_a_fixed_message(
    rig: ItemRig, changes: dict[str, str], message: str
) -> None:
    response = rig.client.post("/tasks", data={**FORM, **changes}, headers=HEADERS)

    assert response.status_code == 200
    assert "hx-redirect" not in response.headers
    assert error_text(response.text) == message
    assert [e for e in rig.ledger.events.query(everything()) if e.source == "local"] == []


def test_a_bad_form_keeps_what_was_typed_and_never_echoes_it_in_the_message(
    rig: ItemRig,
) -> None:
    response = rig.client.post(
        "/tasks", data={**FORM, "title": "<b>x</b>" + "t" * MAX_TITLE}, headers=HEADERS
    )

    assert "&lt;b&gt;x&lt;/b&gt;" in response.text
    assert "<b>x</b>" not in response.text
    assert "x&lt;/b&gt;" not in error_text(response.text)
    assert '<details class="panel new-task" id="new-task" open>' in response.text


def test_the_form_needs_the_csrf_token(rig: ItemRig) -> None:
    assert rig.client.post("/tasks", data=FORM).status_code == 403


def test_without_an_item_service_the_create_route_is_404(ledger: LedgerRig) -> None:
    bare = make_item_rig(ledger, items=False)

    assert bare.client.post("/tasks", data=FORM, headers=HEADERS).status_code == 404


# ---- check-off, notes, edit and delete --------------------------------------------------------


def test_a_task_can_be_checked_off_and_noted_like_any_item(rig: ItemRig) -> None:
    task_id = create(rig)

    rig.client.post(f"/items/{task_id}/done?ctx=agenda&day={TODAY}", headers=HEADERS)
    rig.client.put(
        f"/items/{task_id}/notes?ctx=agenda&day={TODAY}", data={"text": "page 40"}, headers=HEADERS
    )

    row = row_of(rig.page(), task_id, "agenda")
    assert "Undo" in row
    assert "chip-note" in row
    assert "Done, no priority" in row


def test_only_a_task_has_the_edit_form_and_the_edit_is_prefilled_in_local_time(
    ledger: LedgerRig,
) -> None:
    rig = make_item_rig(ledger)
    rig.seed(assignment("canvas-one", hours=5))
    task_id = create(rig)

    html = rig.page()

    mine = row_of(html, task_id, "agenda")
    assert 'value="Read chapter 4"' in mine
    assert 'name="due_date" type="date" value="2026-11-07"' in mine
    assert 'name="due_time" type="time" value="15:00"' in mine
    assert 'value="BIO 101"' in mine
    assert "Save task" in mine
    assert "Save task" not in row_of(html, "canvas-one", "agenda")
    assert "Delete task" not in row_of(html, "canvas-one", "agenda")


def test_editing_a_task_changes_its_title_due_time_and_label(rig: ItemRig) -> None:
    task_id = create(rig)

    response = rig.client.patch(
        f"/items/{task_id}?ctx=agenda&day={TODAY}",
        data={"title": "Read chapter 5", "due_date": TODAY, "due_time": "18:30", "label": "CHEM"},
        headers=HEADERS,
    )

    row = row_of(response.text, task_id, "agenda")
    assert "Read chapter 5" in row
    assert "Due 18:30" in row
    assert "CHEM" in row
    assert "BIO 101" not in row
    assert "Task saved." in row
    (task,) = [e for e in rig.ledger.events.query(everything()) if e.source == "local"]
    assert task.due == datetime(2026, 11, 8, 1, 30, tzinfo=UTC)


def test_a_blank_label_in_the_edit_form_removes_the_label(rig: ItemRig) -> None:
    task_id = create(rig)

    rig.client.patch(
        f"/items/{task_id}?ctx=agenda&day={TODAY}", data={**FORM, "label": ""}, headers=HEADERS
    )

    assert "chip-label" not in row_of(rig.page(), task_id, "agenda")


def test_a_bad_edit_changes_nothing_and_says_why(rig: ItemRig) -> None:
    task_id = create(rig)

    response = rig.client.patch(
        f"/items/{task_id}?ctx=agenda&day={TODAY}", data={**FORM, "title": ""}, headers=HEADERS
    )

    assert "Title must be 1 to 200 characters." in response.text
    assert 'class="flash bad"' in response.text
    assert "Read chapter 4" in row_of(rig.page(), task_id, "agenda")


def test_an_item_from_a_source_cannot_be_edited_or_deleted_from_the_web(
    ledger: LedgerRig,
) -> None:
    rig = make_item_rig(ledger)
    rig.seed(assignment("c", hours=5, title="From Canvas"))

    patched = rig.client.patch("/items/c?ctx=agenda", data=FORM, headers=HEADERS)
    deleted = rig.client.delete("/items/c?ctx=agenda", headers=HEADERS)

    assert (patched.status_code, deleted.status_code) == (409, 409)
    assert "From Canvas" in rig.page()


def test_edit_and_delete_of_an_unknown_item_are_404(rig: ItemRig) -> None:
    assert rig.client.patch("/items/nope", data=FORM, headers=HEADERS).status_code == 404
    assert rig.client.delete("/items/nope", headers=HEADERS).status_code == 404


def test_deleting_a_task_removes_it_from_every_list_and_takes_its_note_with_it(
    rig: ItemRig,
) -> None:
    task_id = create(rig)
    rig.client.put(
        f"/items/{task_id}/notes?ctx=agenda&day={TODAY}", data={"text": "n"}, headers=HEADERS
    )

    response = rig.client.delete(f"/items/{task_id}?ctx=agenda&day={TODAY}", headers=HEADERS)

    assert response.status_code == 200
    assert f'<li id="row-attention-{task_id}" hx-swap-oob="delete"></li>' in response.text
    assert f'id="row-agenda-{task_id}"' not in response.text
    assert "Read chapter 4" not in rig.page()
    assert rig.ledger.ledger.marks([task_id]) == {}


def test_a_task_checked_off_today_is_in_todays_history(rig: ItemRig) -> None:
    task_id = create(rig)
    rig.client.post(f"/items/{task_id}/done?ctx=agenda&day={TODAY}", headers=HEADERS)

    mine = section(rig.page("/history"), "h-done_by_you")

    assert "Read chapter 4" in mine
    assert "You" in mine
