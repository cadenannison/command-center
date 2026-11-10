"""Entering the Gemini key end to end: API and settings page, the summary, /v1/sync, no leaks."""

import logging
import re
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from builders import NOW, make_event
from command_center.adapters.summary_gemini import GeminiIntegration, GeminiSummaryProvider
from command_center.api import create_app
from command_center.core.summary import DailySummary
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import (
    FakeClock,
    InMemoryEventStore,
    InMemorySecretStore,
    InMemorySummaryStore,
)

DENVER = ZoneInfo("America/Denver")
DAY = "2026-11-07"
KEY = "fake-gemini-key-ABCD1234"
OTHER_KEY = "fake-other-gemini-key-WXYZ9876"
SUMMARY = DailySummary(headline="Busy day", priorities=["Essay"], heads_up=["Quiz Friday"])
TEMPLATE = "template"


class _Models:
    def __init__(self, gemini: "FakeGemini", api_key: str) -> None:
        self._gemini = gemini
        self._api_key = api_key

    async def count_tokens(self, **_: Any) -> object:  # noqa: ANN401
        self._gemini.count_keys.append(self._api_key)
        return self._check()

    async def generate_content(self, **_: Any) -> Any:  # noqa: ANN401
        self._gemini.generate_keys.append(self._api_key)
        self._check()
        return type("Reply", (), {"text": SUMMARY.model_dump_json()})()

    def _check(self) -> object:
        if self._api_key != KEY:
            raise errors.APIError(400, {"error": {"message": f"bad {self._api_key}"}})
        return object()


class _Aio:
    def __init__(self, models: _Models) -> None:
        self.models = models

    async def aclose(self) -> None:
        return None


class _Client:
    def __init__(self, models: _Models) -> None:
        self.aio = _Aio(models)

    def close(self) -> None:
        return None


class FakeGemini:
    """The Gemini API as SDK clients: only KEY is accepted, any other key gets a 400."""

    def __init__(self) -> None:
        self.generate_keys: list[str] = []
        self.count_keys: list[str] = []

    def client(self, api_key: str) -> Any:  # noqa: ANN401
        return _Client(_Models(self, api_key))


class Rig:
    def __init__(self) -> None:
        clock = FakeClock(NOW)
        self.gemini = FakeGemini()
        self.secrets = InMemorySecretStore()
        events = InMemoryEventStore()
        events.upsert(
            [
                make_event(id="essay", title="Essay draft", start=NOW),
                make_event(id="quiz", title="Quiz", start=NOW + timedelta(days=1)),
            ]
        )
        self.canvas = FakeAdapter("canvas")
        adapters = {"canvas": self.canvas}
        self.sync = SyncService(adapters, self.secrets, events, clock, sleep=RecordingSleep())
        agenda = AgendaService(events, clock, DENVER)
        factory = self.gemini.client
        self.summary_store = InMemorySummaryStore()
        self.container = Container(
            sync=self.sync,
            agenda=agenda,
            settings=SettingsService(
                adapters,
                self.secrets,
                self.sync,
                {"gemini": GeminiIntegration(model="fake-model", client_factory=factory)},
            ),
            summary=SummaryService(
                agenda,
                self.summary_store,
                GeminiSummaryProvider(self.secrets, model="fake-model", client_factory=factory),
                clock,
                DENVER,
            ),
        )


@pytest.fixture
def rig() -> Rig:
    return Rig()


@pytest.fixture
def client(rig: Rig) -> Iterator[TestClient]:
    with TestClient(create_app(rig.container), base_url="http://localhost") as found:
        yield found


def put_key(client: TestClient, value: str = KEY) -> dict[str, Any]:
    return client.put("/v1/settings/gemini", json={"credentials": {"api_key": value}}).json()


def summary_provider(client: TestClient, day: str = DAY) -> str:
    return client.get("/v1/summary", params={"date": day}).json()["provider"]


def test_before_a_key_is_saved_the_summary_is_the_template_and_gemini_is_not_called(
    client: TestClient, rig: Rig
) -> None:
    assert summary_provider(client) == TEMPLATE
    assert rig.gemini.generate_keys == []


def test_the_key_is_listed_as_set_with_its_last4_and_no_sync_state(client: TestClient) -> None:
    put_key(client)

    listed = {item["source"]: item for item in client.get("/v1/settings").json()}

    assert listed["gemini"]["keys"] == {"api_key": {"set": True, "last4": "1234"}}
    assert listed["gemini"]["sync"] is None


def test_saving_the_key_returns_ok_with_no_sync_and_stores_it(client: TestClient, rig: Rig) -> None:
    result = put_key(client)

    assert (result["ok"], result["sync"]) == (True, None)
    assert dict(rig.secrets.get("gemini")) == {"api_key": KEY}
    assert rig.canvas.fetches == []  # no background sync was queued for it


def test_a_rejected_key_is_ok_false_and_nothing_is_stored(client: TestClient, rig: Rig) -> None:
    result = put_key(client, OTHER_KEY)

    assert (result["ok"], result["message"]) == (False, "Gemini rejected the API key")
    assert dict(rig.secrets.get("gemini")) == {}


def test_once_saved_the_summary_is_built_by_gemini_without_a_restart(
    client: TestClient, rig: Rig
) -> None:
    put_key(client)

    body = client.get("/v1/summary", params={"date": DAY}).json()

    assert (body["provider"], body["cached"]) == ("gemini", False)
    assert body["summary"]["headline"] == "Busy day"
    assert rig.gemini.generate_keys == [KEY]


def test_replacing_the_key_applies_to_the_next_summary(client: TestClient, rig: Rig) -> None:
    put_key(client)
    assert put_key(client, OTHER_KEY)["ok"] is False  # the old, valid key stays

    assert summary_provider(client) == "gemini"
    assert rig.gemini.generate_keys == [KEY]


def test_deleting_the_key_before_any_summary_returns_the_day_to_the_template(
    client: TestClient, rig: Rig
) -> None:
    put_key(client)

    deleted = client.delete("/v1/settings/gemini").json()

    assert deleted == {"source": "gemini", "keys": {}, "sync": None, "values": {}}
    assert summary_provider(client) == TEMPLATE  # DAY has an event, so only the key is missing
    assert rig.gemini.generate_keys == []


def test_after_a_delete_a_new_day_gets_the_earlier_stored_summary_and_gemini_is_not_called(
    client: TestClient, rig: Rig
) -> None:
    put_key(client)
    assert summary_provider(client) == "gemini"

    client.delete("/v1/settings/gemini")

    assert summary_provider(client) == "gemini"  # the day's stored summary stands (decision 0058)
    assert summary_provider(client, "2026-11-08") == "stored"
    assert rig.gemini.generate_keys == [KEY]  # the one call made while the key existed


def test_deleting_the_key_leaves_the_state_where_nothing_was_ever_saved(
    client: TestClient,
) -> None:
    put_key(client)
    client.delete("/v1/settings/gemini")

    listed = {item["source"]: item for item in client.get("/v1/settings").json()}

    assert listed["gemini"] == {"source": "gemini", "keys": {}, "sync": None, "values": {}}


def test_sync_ignores_the_key_and_the_integration(client: TestClient, rig: Rig) -> None:
    put_key(client)

    states = client.post("/v1/sync").json()

    assert [state["source"] for state in states] == ["canvas"]
    assert rig.sync.sources() == ["canvas"]
    assert rig.sync.state("gemini") is None


def test_the_key_is_not_in_any_api_response_or_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    bodies: list[str] = []
    with caplog.at_level(logging.DEBUG):
        bodies += [
            client.put("/v1/settings/gemini", json={"credentials": {"api_key": candidate}}).text
            for candidate in (OTHER_KEY, KEY)
        ]
        bodies += [
            client.get("/v1/settings").text,
            client.post("/v1/sync").text,
            client.get("/v1/summary", params={"date": DAY}).text,
            client.delete("/v1/settings/gemini").text,
            client.get("/v1/summary", params={"date": "2026-11-08"}).text,
            client.put("/v1/settings/gemini", json={"credentials": {"api_key": ""}}).text,
        ]

    leaked = [
        secret for secret in (KEY, OTHER_KEY) for text in (*bodies, caplog.text) if secret in text
    ]
    assert leaked == []


def csrf_token(client: TestClient) -> str:
    match = re.search(r'"X-CSRF-Token": "([^"]+)"', client.get("/settings").text)
    assert match is not None
    return match.group(1)


def gemini_card(html: str) -> str:
    match = re.search(
        r'<section[^>]*aria-labelledby="h-gemini".*?</section>', html, flags=re.DOTALL
    )
    assert match is not None
    return match.group(0)


def test_the_settings_page_has_a_gemini_card_with_the_caveat_and_the_redaction_note(
    client: TestClient,
) -> None:
    card = gemini_card(client.get("/settings").text)

    assert "Gemini summaries" in card
    assert "free tier" in card
    assert "improve its products" in card
    assert "redacted" in card
    assert "never email bodies" in card
    assert 'type="password"' in card
    assert "Not connected" in card


def test_saving_in_the_page_shows_connected_and_last4_and_never_the_key(
    client: TestClient, rig: Rig
) -> None:
    token = {"X-CSRF-Token": csrf_token(client)}

    html = client.put("/settings/gemini", data={"api_key": KEY}, headers=token).text
    page = client.get("/settings").text

    assert "Connected" in gemini_card(page)
    assert "ends 1234" in gemini_card(page)
    assert "hx-trigger" not in gemini_card(html)  # nothing to poll: there is no sync
    assert KEY not in html + page
    assert dict(rig.secrets.get("gemini")) == {"api_key": KEY}
    assert rig.canvas.fetches == []


def test_a_rejected_key_in_the_page_says_so_and_stores_nothing(
    client: TestClient, rig: Rig
) -> None:
    token = {"X-CSRF-Token": csrf_token(client)}

    html = client.put("/settings/gemini", data={"api_key": OTHER_KEY}, headers=token).text

    assert "Gemini rejected the API key" in html
    assert OTHER_KEY not in html
    assert dict(rig.secrets.get("gemini")) == {}


def test_deleting_in_the_page_clears_the_card_and_asks_about_the_key_not_synced_items(
    client: TestClient, rig: Rig
) -> None:
    token = {"X-CSRF-Token": csrf_token(client)}
    client.put("/settings/gemini", data={"api_key": KEY}, headers=token)

    html = client.delete("/settings/gemini", headers=token).text

    assert dict(rig.secrets.get("gemini")) == {}
    assert "Not connected" in gemini_card(html)
    assert "synced items" not in gemini_card(html)
