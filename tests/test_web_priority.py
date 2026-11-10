"""The priority badge on every row of Today, Week and Month, and priority in the API."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from builders import NOW, make_event
from command_center.api import create_app
from web_rig import WebRig, make_rig

PRIORITY_BADGE = re.compile(
    r'<span class="prio" style="--p:(\d+)" title="Priority (\d+) of 10">'
    r'<span class="visually-hidden">Priority </span>(\d+)</span>'
)


@pytest.fixture
def rig() -> WebRig:
    found = make_rig()
    found.seed(
        make_event(id="due", kind="assignment", title="Essay", due=NOW + timedelta(hours=5)),
        make_event(
            id="done",
            kind="assignment",
            title="Old essay",
            due=NOW + timedelta(hours=6),
            status="done",
        ),
    )
    return found


@pytest.mark.parametrize("path", ["/", "/week", "/month"])
def test_a_due_soon_assignment_shows_priority_9_and_prints_the_number(
    rig: WebRig, path: str
) -> None:
    badge = PRIORITY_BADGE.search(rig.client.get(path).text)

    assert badge is not None
    assert badge.groups() == ("9", "9", "9")


@pytest.mark.parametrize("path", ["/", "/week"])
def test_a_done_item_gets_a_dash_and_never_a_number(rig: WebRig, path: str) -> None:
    html = rig.client.get(path).text

    done_row = html.split("Old essay")[1].split("</li>")[0]

    assert '<span class="prio none"' in done_row
    assert "No priority: done or ended" in done_row
    assert '<span class="prio" ' not in done_row


def test_the_colour_is_a_computed_hue_with_a_dark_theme_rule(rig: WebRig) -> None:
    html = rig.client.get("/").text

    assert "--hue:calc(120 - (var(--p, 1) - 1) * 13.333)" in html
    assert "@media (prefers-color-scheme:dark){.prio{" in html


def test_the_agenda_api_carries_priority_beside_urgency(rig: WebRig) -> None:
    with TestClient(create_app(rig.container), base_url="http://localhost") as client:
        events = client.get("/v1/agenda/day", params={"date": "2026-11-07"}).json()

    by_id = {event["id"]: event for event in events}
    assert (by_id["due"]["urgency"], by_id["due"]["priority"]) == (90, 9)
    assert by_id["done"]["priority"] is None
