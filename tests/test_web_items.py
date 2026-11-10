"""Check-off, undo, notes and the reason tooltip on the pages (decisions 0150 to 0152)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from markupsafe import escape

from command_center.core.ledger import MAX_NOTE
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine
from web_items_support import (
    HEADERS,
    ItemRig,
    an_event,
    due_soon,
    make_item_rig,
    row_of,
    section,
)


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> ItemRig:
    found = make_item_rig(ledger)
    found.seed(due_soon("a", title="Essay"), an_event("e"))
    return found


def attr(url: str) -> str:
    """A URL as it sits inside an HTML attribute."""
    return url.replace("&", "&amp;")


def done_path(item_id: str, ctx: str = "agenda") -> str:
    return f"/items/{item_id}/done?ctx={ctx}&day=2026-11-07&dated=0"


def notes_path(item_id: str, ctx: str = "agenda") -> str:
    return f"/items/{item_id}/notes?ctx={ctx}&day=2026-11-07&dated=0"


# ---- the controls -----------------------------------------------------------------------------


def test_every_agenda_row_has_a_done_button_that_posts_to_its_own_item(rig: ItemRig) -> None:
    html = rig.page()

    assert f'hx-post="{attr(done_path("a"))}"' in row_of(html, "a", "agenda")
    assert f'hx-post="{attr(done_path("e"))}"' in row_of(html, "e", "agenda")


def test_the_attention_list_and_the_week_and_month_pages_have_the_controls_too(
    rig: ItemRig,
) -> None:
    assert 'hx-post="/items/a/done?ctx=attention&amp;dated=1"' in row_of(
        rig.page(), "a", "attention"
    )
    assert "/items/a/done?ctx=week&amp;day=2026-11-07" in row_of(rig.page("/week"), "a", "week")
    assert "/items/a/done?ctx=deadline&amp;dated=1" in row_of(rig.page("/month"), "a", "deadline")


def test_without_an_item_service_there_are_no_controls_and_no_history(ledger: LedgerRig) -> None:
    bare = make_item_rig(ledger, items=False)
    bare.seed(due_soon("a"))

    html = bare.page()

    assert "hx-post" not in section(html, "agenda-h")
    assert "New task" not in html
    assert bare.client.get("/history").status_code == 404
    assert bare.client.post("/items/a/done", headers=HEADERS).status_code == 404


def test_the_main_nav_links_to_history(rig: ItemRig) -> None:
    assert '<a href="/history">History</a>' in rig.page()
    assert 'aria-current="page">History</a>' in rig.page("/history")


# ---- check-off and undo -----------------------------------------------------------------------


def test_check_off_answers_with_the_row_struck_through_and_an_undo_button(rig: ItemRig) -> None:
    response = rig.client.post(done_path("a"), headers=HEADERS)

    assert response.status_code == 200
    row = row_of(response.text, "a", "agenda")
    assert 'class="row kind-assignment done"' in row
    assert "Undo" in row
    assert '<span class="prio none"' in row
    assert f'hx-delete="{attr(done_path("a"))}"' in row


def test_check_off_from_the_agenda_also_removes_the_attention_copy(rig: ItemRig) -> None:
    response = rig.client.post(done_path("a", "agenda"), headers=HEADERS)

    assert '<li id="row-attention-a" hx-swap-oob="delete"></li>' in response.text


def test_check_off_from_the_attention_list_keeps_that_row_so_it_can_be_undone(
    rig: ItemRig,
) -> None:
    response = rig.client.post("/items/a/done?ctx=attention&dated=1", headers=HEADERS)

    assert "hx-swap-oob" not in response.text
    assert "Undo" in row_of(response.text, "a", "attention")


def test_a_checked_off_item_is_struck_through_on_reload_and_leaves_the_attention_list(
    rig: ItemRig,
) -> None:
    rig.client.post(done_path("a"), headers=HEADERS)

    html = rig.page()

    assert 'id="row-attention-a"' not in html
    assert "Nothing needs attention." in section(html, "attention-h")
    assert 'class="row kind-assignment done"' in row_of(html, "a", "agenda")


def test_undo_brings_back_the_done_button_and_the_priority(rig: ItemRig) -> None:
    rig.client.post(done_path("a"), headers=HEADERS)
    path = done_path("a")

    response = rig.client.delete(path, headers=HEADERS)

    row = row_of(response.text, "a", "agenda")
    assert response.status_code == 200
    assert "Undo" not in row
    assert 'hx-post="/items/a/done' in row
    assert 'title="Priority 9 of 10"' in row


def test_an_item_the_source_reports_done_has_no_undo(ledger: LedgerRig) -> None:
    rig = make_item_rig(ledger)
    rig.seed(assignment("s", hours=5, status="done", title="Handed in"))

    row = row_of(rig.page(), "s", "agenda")

    assert 'title="The source reports this done"' in row
    assert "Undo" not in row


def test_check_off_and_undo_of_an_unknown_item_are_404(rig: ItemRig) -> None:
    assert rig.client.post(done_path("nope"), headers=HEADERS).status_code == 404
    assert rig.client.delete(done_path("nope"), headers=HEADERS).status_code == 404


def test_a_write_without_the_csrf_token_is_403_and_changes_nothing(rig: ItemRig) -> None:
    assert rig.client.post(done_path("a")).status_code == 403

    assert 'hx-post="/items/a/done' in row_of(rig.page(), "a", "agenda")


def test_a_bad_ctx_is_422(rig: ItemRig) -> None:
    response = rig.client.post("/items/a/done?ctx=evil", headers=HEADERS)

    assert response.status_code == 422


# ---- notes ------------------------------------------------------------------------------------


def test_saving_a_note_shows_the_has_note_marker_and_the_text(rig: ItemRig) -> None:
    response = rig.client.put(notes_path("a"), data={"text": "bring the form"}, headers=HEADERS)

    row = row_of(response.text, "a", "agenda")
    assert 'class="chip chip-note"' in row
    assert "bring the form</textarea>" in row
    assert "Note saved." in row
    assert " open>" in row


def test_the_has_note_marker_and_note_survive_a_reload_on_every_page(rig: ItemRig) -> None:
    rig.client.put(notes_path("a"), data={"text": "bring the form"}, headers=HEADERS)

    for path, ctx in (("/", "agenda"), ("/week", "week"), ("/month", "deadline")):
        row = row_of(rig.page(path), "a", ctx)
        assert 'class="chip chip-note"' in row
        assert "bring the form</textarea>" in row


def test_an_item_without_a_note_has_no_marker(rig: ItemRig) -> None:
    assert "chip-note" not in row_of(rig.page(), "a", "agenda")


def test_deleting_a_note_removes_the_marker_and_the_text(rig: ItemRig) -> None:
    rig.client.put(notes_path("a"), data={"text": "bring the form"}, headers=HEADERS)

    response = rig.client.delete(notes_path("a"), headers=HEADERS)

    row = row_of(response.text, "a", "agenda")
    assert "chip-note" not in row
    assert "bring the form" not in row
    assert "Note deleted." in row


def test_a_blank_note_is_refused_with_a_message_and_nothing_is_stored(rig: ItemRig) -> None:
    response = rig.client.put(notes_path("a"), data={"text": "   "}, headers=HEADERS)

    assert response.status_code == 200
    assert 'class="flash bad"' in row_of(response.text, "a", "agenda")
    assert "chip-note" not in row_of(rig.page(), "a", "agenda")


def test_a_too_long_note_is_refused_and_the_typed_text_stays_in_the_box(rig: ItemRig) -> None:
    typed = "x" * (MAX_NOTE + 1)

    response = rig.client.put(notes_path("a"), data={"text": typed}, headers=HEADERS)

    row = row_of(response.text, "a", "agenda")
    assert "must be 1 to 4000 characters" in row
    assert typed in row
    assert "chip-note" not in row_of(rig.page(), "a", "agenda")


def test_a_note_of_the_longest_allowed_size_is_saved(rig: ItemRig) -> None:
    response = rig.client.put(notes_path("a"), data={"text": "y" * MAX_NOTE}, headers=HEADERS)

    assert "Note saved." in response.text


def test_note_and_title_markup_is_escaped_on_the_page_and_in_the_fragment(
    ledger: LedgerRig,
) -> None:
    rig = make_item_rig(ledger)
    rig.seed(due_soon("a", title="<script>alert(1)</script> Essay"))
    note = '</textarea><img src=x onerror=alert(2)> & "quoted"'

    fragment = rig.client.put(notes_path("a"), data={"text": note}, headers=HEADERS).text
    page = rig.page()

    for html in (fragment, page):
        assert "<script>alert(1)" not in html
        assert "<img src=x" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt; Essay" in html
        assert str(escape(note)) in html


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(text=st.text(alphabet="<>&\"' ab/=\n", min_size=1, max_size=60).filter(lambda t: t.strip()))
def test_no_note_text_is_ever_written_raw(rig: ItemRig, text: str) -> None:
    rig.client.put(notes_path("a"), data={"text": text}, headers=HEADERS)

    html = rig.page()

    assert str(escape(text.rstrip())) in html
    assert "<b" not in html.split("</textarea>")[0].split("<textarea")[-1]


def test_note_routes_404_for_an_unknown_item(rig: ItemRig) -> None:
    assert (
        rig.client.put(notes_path("nope"), data={"text": "x"}, headers=HEADERS).status_code == 404
    )
    assert rig.client.delete(notes_path("nope"), headers=HEADERS).status_code == 404


# ---- why this priority ------------------------------------------------------------------------


def test_the_badge_shows_the_reason_as_a_tooltip_on_a_wrapper(rig: ItemRig) -> None:
    row = row_of(rig.page(), "a", "agenda")

    assert '<span class="why" title="Due in 5 hours, not submitted">' in row
    assert re.search(r'title="Priority 9 of 10"', row)


def test_the_item_details_say_why_this_priority(rig: ItemRig) -> None:
    row = row_of(rig.page(), "a", "agenda")

    assert "<strong>Why this priority:</strong> Due in 5 hours, not submitted" in row


def test_a_checked_off_item_explains_that_it_is_done(rig: ItemRig) -> None:
    rig.client.post(done_path("a"), headers=HEADERS)

    row = row_of(rig.page(), "a", "agenda")

    assert 'title="Done, no priority"' in row


def test_the_reason_is_shown_even_without_an_item_service(ledger: LedgerRig) -> None:
    bare = make_item_rig(ledger, items=False)
    bare.seed(due_soon("a"))

    assert 'title="Due in 5 hours, not submitted"' in bare.page()
