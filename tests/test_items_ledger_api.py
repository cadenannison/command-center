"""The check-off, note and history routes over the real SQL ledger (decisions 0120 to 0125)."""

import logging
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from builders import NOW
from command_center.api import create_app
from command_center.core.ledger import MAX_NOTE
from command_center.core.windows import TimeWindow
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_items import create_item_ledger
from fakes import FakeSummaryProvider, InMemorySecretStore, InMemorySummaryStore
from ledger_support import DENVER, LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine
from summary_support import GOOD

EVERYTHING = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))
NEEDLE = "fake-note-needle-8c41"
TODAY = "2026-11-07"  # NOW is 05:00 on this day in America/Denver


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def client(rig: LedgerRig) -> TestClient:
    secrets = InMemorySecretStore()
    sync = SyncService({}, secrets, rig.events, rig.clock, ledger=rig.ledger)
    container = Container(
        sync=sync,
        agenda=rig.agenda,
        settings=SettingsService({}, secrets, sync),
        items=rig.items,
    )
    return TestClient(create_app(container), base_url="http://localhost")


def seed(rig: LedgerRig, item_id: str = "a", *, title: str | None = None) -> str:
    """An assignment due an hour after NOW: inside TODAY and urgent."""
    rig.events.upsert([assignment(item_id, hours=1, title=title)])
    return item_id


def agenda(client: TestClient) -> dict[str, Any]:
    response = client.get("/v1/agenda/day", params={"date": TODAY})
    assert response.status_code == 200
    return {item["id"]: item for item in response.json()}


# ---- check off ---------------------------------------------------------------------------------


def test_checking_an_item_off_marks_it_done_and_clears_its_urgency(
    rig: LedgerRig, client: TestClient
) -> None:
    seed(rig)
    assert agenda(client)["a"]["urgency"] > 0

    response = client.post("/v1/items/a/done")

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["urgency"], body["priority"]) == ("done", 0, None)
    assert agenda(client)["a"]["status"] == "done"


def test_a_checked_off_item_leaves_the_attention_list(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    assert [i["id"] for i in client.get("/v1/attention").json()] == ["a"]

    client.post("/v1/items/a/done")

    assert client.get("/v1/attention").json() == []


def test_undoing_a_check_off_brings_the_item_back(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    client.post("/v1/items/a/done")

    response = client.delete("/v1/items/a/done")

    assert response.status_code == 200
    assert response.json()["status"] is None
    assert [i["id"] for i in client.get("/v1/attention").json()] == ["a"]


def test_checking_off_twice_keeps_the_first_time(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    client.post("/v1/items/a/done")
    rig.clock.advance(timedelta(hours=3))
    client.post("/v1/items/a/done")

    (entry,) = rig.ledger.history(EVERYTHING)
    assert entry.at == NOW


def test_undoing_when_the_source_says_done_leaves_it_done(
    rig: LedgerRig, client: TestClient
) -> None:
    rig.events.upsert([assignment("a")])
    rig.events.replace("canvas", EVERYTHING, [assignment("a", status="done")])

    response = client.delete("/v1/items/a/done")

    assert response.json()["status"] == "done"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/items/nope/done"),
        ("DELETE", "/v1/items/nope/done"),
        ("DELETE", "/v1/items/nope/notes"),
    ],
)
def test_an_unknown_item_is_404(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)
    assert (response.status_code, response.json()) == (404, {"detail": "No such item"})


def test_an_unknown_item_cannot_get_a_note(client: TestClient) -> None:
    assert client.put("/v1/items/nope/notes", json={"text": "hi"}).status_code == 404


# ---- notes -------------------------------------------------------------------------------------


def test_a_note_marks_the_item_in_every_agenda_view(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    assert agenda(client)["a"]["has_note"] is False

    response = client.put("/v1/items/a/notes", json={"text": "bring the lab report"})

    assert response.status_code == 200
    assert response.json()["has_note"] is True
    assert agenda(client)["a"]["has_note"] is True
    events = client.get(
        "/v1/events", params={"from": "2026-11-07T00:00:00Z", "to": "2026-11-09T00:00:00Z"}
    ).json()
    assert [e["has_note"] for e in events] == [True]


def test_the_note_text_is_never_part_of_an_agenda_item(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    client.put("/v1/items/a/notes", json={"text": NEEDLE})

    assert NEEDLE not in client.get("/v1/agenda/day", params={"date": TODAY}).text
    assert NEEDLE not in client.get("/v1/attention").text


def test_a_note_replaces_the_previous_one(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    client.put("/v1/items/a/notes", json={"text": "first"})
    client.put("/v1/items/a/notes", json={"text": "second"})

    assert rig.ledger.marks(["a"])["a"].note == "second"


def test_a_note_of_exactly_4000_characters_is_accepted(rig: LedgerRig, client: TestClient) -> None:
    seed(rig)
    response = client.put("/v1/items/a/notes", json={"text": "x" * MAX_NOTE})
    assert response.status_code == 200
    assert len(rig.ledger.marks(["a"])["a"].note or "") == MAX_NOTE


@pytest.mark.parametrize("body", [{"text": "x" * (MAX_NOTE + 1)}, {"text": "   \n"}, {"text": ""}])
def test_a_note_over_4000_or_blank_is_422_and_the_response_does_not_echo_it(
    rig: LedgerRig, client: TestClient, body: dict[str, str]
) -> None:
    seed(rig)
    response = client.put("/v1/items/a/notes", json=body)
    assert response.status_code == 422
    assert "note must be 1 to 4000 characters" in response.text
    assert body["text"].strip() == "" or "xxxxxxxxxx" not in response.text
    assert rig.ledger.marks(["a"]) == {}


def test_a_note_with_markup_comes_back_as_plain_json_text(
    rig: LedgerRig, client: TestClient
) -> None:
    seed(rig)
    markup = '<script>alert("x")</script> & more'
    client.put("/v1/items/a/notes", json={"text": markup})
    client.post("/v1/items/a/done")

    response = client.get("/v1/history", params={"from": TODAY, "to": TODAY})

    assert response.headers["content-type"] == "application/json"
    assert response.json()[0]["done_by_you"][0]["note"] == markup


def test_deleting_a_note_clears_the_flag_and_is_harmless_when_there_is_none(
    rig: LedgerRig, client: TestClient
) -> None:
    seed(rig)
    client.put("/v1/items/a/notes", json={"text": "temp"})

    first = client.delete("/v1/items/a/notes")
    again = client.delete("/v1/items/a/notes")

    assert (first.status_code, first.json()["has_note"]) == (200, False)
    assert (again.status_code, again.json()["has_note"]) == (200, False)
    assert rig.ledger.marks(["a"]) == {}


def test_a_note_is_never_logged(
    rig: LedgerRig, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    seed(rig)
    caplog.set_level(logging.DEBUG)

    client.put("/v1/items/a/notes", json={"text": NEEDLE})
    client.get("/v1/history", params={"from": TODAY, "to": TODAY})
    client.delete("/v1/items/a/notes")

    assert NEEDLE not in caplog.text
    assert all(NEEDLE not in str(record.args) for record in caplog.records)


def test_a_database_error_while_saving_a_note_does_not_carry_the_note(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    events = create_event_store(url)
    ledger = create_item_ledger(url)  # the production factories hide statement parameters
    events.upsert([assignment("a")])
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER no_ledger_rows BEFORE INSERT ON item_ledger "
                "BEGIN SELECT RAISE(ABORT, 'boom'); END"
            )
        )
    admin.dispose()

    with pytest.raises(DBAPIError, match="boom") as raised:
        ledger.set_note("a", NEEDLE, NOW)

    assert NEEDLE not in str(raised.value)
    assert NEEDLE not in repr(raised.value)


async def test_a_note_is_not_in_what_a_summary_provider_is_sent(rig: LedgerRig) -> None:
    seed(rig, title="Lab report")
    await rig.items.set_note("a", NEEDLE)
    provider = FakeSummaryProvider(GOOD)
    service = SummaryService(
        AgendaService(rig.events, rig.clock, DENVER, rig.ledger),
        InMemorySummaryStore(),
        provider,
        rig.clock,
        DENVER,
        include_email=False,
    )

    await service.get(date(2026, 11, 7))

    (prompt,) = provider.prompts
    assert "Lab report" in prompt
    assert NEEDLE not in prompt


# ---- history -----------------------------------------------------------------------------------


def test_history_returns_days_with_title_source_completed_by_and_note(
    rig: LedgerRig, client: TestClient
) -> None:
    seed(rig, "mine", title="Essay")
    seed(rig, "theirs", title="Quiz")
    client.put("/v1/items/mine/notes", json={"text": "draft two"})
    client.post("/v1/items/mine/done")
    rig.events.replace(
        "canvas",
        EVERYTHING,
        [assignment("mine"), assignment("theirs", status="done", title="Quiz")],
    )
    rig.events.replace("canvas", EVERYTHING, [assignment("mine")])

    response = client.get("/v1/history", params={"from": TODAY, "to": TODAY})

    assert response.status_code == 200
    (day,) = response.json()
    assert day["day"] == TODAY
    (you,) = day["done_by_you"]
    assert (you["title"], you["source"], you["completed_by"], you["note"]) == (
        "Essay",
        "canvas",
        "user",
        "draft two",
    )
    (source,) = day["done_by_source"]
    assert (source["title"], source["completed_by"], source["note"]) == ("Quiz", "source", None)
    assert day["gone"] == []


def test_history_tags_an_item_the_source_completed_and_later_reopened(
    rig: LedgerRig, client: TestClient
) -> None:
    rig.events.replace("canvas", EVERYTHING, [assignment("quiz", status="done", title="Quiz")])
    rig.clock.advance(timedelta(days=1))
    rig.events.replace("canvas", EVERYTHING, [assignment("quiz", title="Quiz")])

    (day,) = client.get("/v1/history", params={"from": TODAY, "to": TODAY}).json()

    assert [(e["title"], e["reopened"]) for e in day["done_by_source"]] == [("Quiz", True)]


def test_history_does_not_tag_an_item_that_is_still_done_or_that_you_checked_off(
    rig: LedgerRig, client: TestClient
) -> None:
    seed(rig, "mine")
    client.post("/v1/items/mine/done")
    rig.events.replace(
        "canvas", EVERYTHING, [assignment("kept", status="done"), assignment("mine")]
    )

    (day,) = client.get("/v1/history", params={"from": TODAY, "to": TODAY}).json()

    assert [e["reopened"] for e in day["done_by_you"] + day["done_by_source"]] == [False, False]


def test_a_reopened_item_is_open_in_the_agenda_while_it_stays_in_history(
    rig: LedgerRig, client: TestClient
) -> None:
    rig.events.replace("canvas", EVERYTHING, [assignment("a", hours=1, status="done")])
    rig.events.replace("canvas", EVERYTHING, [assignment("a", hours=1)])

    assert agenda(client)["a"]["status"] != "done"
    (day,) = client.get("/v1/history", params={"from": TODAY, "to": TODAY}).json()
    assert [e["item_id"] for e in day["done_by_source"]] == ["a"]


def test_history_of_an_empty_range_is_an_empty_list(client: TestClient) -> None:
    response = client.get("/v1/history", params={"from": TODAY, "to": TODAY})
    assert (response.status_code, response.json()) == (200, [])


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-08", "to": "2026-11-07"},
        {"from": "2025-11-06", "to": "2026-11-07"},
        {"from": TODAY},
        {"from": "not-a-date", "to": TODAY},
    ],
)
def test_a_bad_history_range_is_422(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/v1/history", params=params).status_code == 422


def test_a_history_range_of_366_days_inclusive_is_accepted(client: TestClient) -> None:
    response = client.get("/v1/history", params={"from": "2025-11-07", "to": "2026-11-07"})
    assert response.status_code == 200


def test_the_item_routes_are_404_while_no_item_service_is_wired(rig: LedgerRig) -> None:
    secrets = InMemorySecretStore()
    sync = SyncService({}, secrets, rig.events, rig.clock)
    container = Container(sync=sync, agenda=rig.agenda, settings=SettingsService({}, secrets, sync))
    bare = TestClient(create_app(container), base_url="http://localhost")

    assert bare.post("/v1/items/a/done").status_code == 404
    assert bare.get("/v1/history", params={"from": TODAY, "to": TODAY}).status_code == 404
