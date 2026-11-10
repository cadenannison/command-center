"""htmx swaps no 4xx reply, so one global listener shows the server's text in the row (0212)."""

import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest

from command_center.web.item_routes import NO_SUCH_ITEM, NOT_LOCAL
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine
from web_items_support import HEADERS, ItemRig, due_soon, make_item_rig, row_of

CSRF_TEXT = "CSRF token missing or wrong"


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> ItemRig:
    found = make_item_rig(ledger)
    found.seed(due_soon("a", title="Essay"))
    return found


def page_script(html: str) -> str:
    """The page's inline script, the one without a `src`."""
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match is not None, "the page has no inline script"
    return match.group(1)


@pytest.mark.parametrize("path", ["/", "/week", "/month", "/history", "/settings"])
def test_every_page_declares_the_handler_for_response_errors(rig: ItemRig, path: str) -> None:
    script = page_script(rig.page(path))

    assert "htmx:responseError" in script
    assert "detail" in script  # reads the server's {"detail": ...} text


def test_the_handler_writes_with_textcontent_never_innerhtml(rig: ItemRig) -> None:
    script = page_script(rig.page())

    assert "textContent" in script
    assert "innerHTML" not in script


SCOPE = 'closest("li, .card, .panel")'  # the listener's search scope; the test below mirrors it


class _Scopes(HTMLParser):
    """Finds, for every htmx control, whether its nearest li, .card or .panel holds a .flash."""

    VOID = frozenset({"input", "br", "meta", "link", "img", "hr"})
    VERBS = ("hx-post", "hx-put", "hx-patch", "hx-delete")

    def __init__(self) -> None:
        super().__init__()
        self._stack: list[tuple[str, dict[str, bool] | None]] = []
        self.controls: list[tuple[str, dict[str, bool] | None]] = []

    def _nearest_scope(self) -> dict[str, bool] | None:
        return next((scope for _, scope in reversed(self._stack) if scope is not None), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = dict(attrs)
        classes = set((names.get("class") or "").split())
        if "flash" in classes:
            for _, scope in self._stack:
                if scope is not None:
                    scope["flash"] = True
        if tag in self.VOID:
            return
        is_scope = tag == "li" or bool({"card", "panel"} & classes)
        self._stack.append((tag, {"flash": False} if is_scope else None))
        verb = next((v for v in self.VERBS if v in names), None)
        if verb is not None:
            self.controls.append((names[verb] or "", self._nearest_scope()))

    def handle_endtag(self, tag: str) -> None:
        while self._stack and self._stack.pop()[0] != tag:
            pass


def test_every_item_control_has_a_flash_in_the_scope_the_listener_searches(rig: ItemRig) -> None:
    made = rig.client.post(
        "/tasks",
        data={"title": "Mine", "due_date": "2026-11-07", "due_time": "10:00", "label": ""},
        headers=HEADERS,
    )
    assert made.status_code == 200
    html = rig.page()
    assert SCOPE in page_script(html)
    scopes = _Scopes()
    scopes.feed(html)

    paths = [path for path, _ in scopes.controls]
    assert any(p.startswith("/items/") and "/notes" in p for p in paths)  # Save note
    assert any(p.startswith("/items/") and "/notes" not in p and "/done" not in p for p in paths)
    assert "/tasks" in paths
    stranded = [path for path, scope in scopes.controls if scope is None or not scope["flash"]]
    assert stranded == []


def test_a_synced_item_edit_answers_409_with_the_text_the_row_will_show(rig: ItemRig) -> None:
    response = rig.client.patch(
        "/items/a?ctx=agenda",
        data={"title": "X", "due_date": "2026-11-07", "due_time": "10:00"},
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": NOT_LOCAL}


def test_a_deleted_item_answers_404_with_the_text_the_row_will_show(rig: ItemRig) -> None:
    response = rig.client.post("/items/gone/done?ctx=agenda", headers=HEADERS)

    assert response.status_code == 404
    assert response.json() == {"detail": NO_SUCH_ITEM}


def test_a_missing_csrf_token_answers_403_with_the_text_the_row_will_show(rig: ItemRig) -> None:
    response = rig.client.post("/items/a/done?ctx=agenda")

    assert response.status_code == 403
    assert response.json() == {"detail": CSRF_TEXT}


def test_each_item_row_has_a_flash_area_inside_the_row_for_the_message(rig: ItemRig) -> None:
    row = row_of(rig.page(), "a", "agenda")

    assert 'class="flash' in row
    assert 'role="status"' in row


def test_the_new_task_panel_has_a_flash_area_for_the_message(rig: ItemRig) -> None:
    assert 'class="flash bad"' in rig.page()
