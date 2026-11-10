"""The web pages over the real SQL item ledger and a fake clock (decisions 0150 to 0153)."""

import re
from dataclasses import dataclass
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from builders import NOW, make_event
from command_center.core.schema import Event
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from command_center.web import create_router
from fakes import InMemorySecretStore
from ledger_support import LedgerRig, assignment

CSRF = "fake-csrf-token-for-tests"
TODAY = "2026-11-07"  # NOW is 05:00 on this day in America/Denver
HEADERS = {"X-CSRF-Token": CSRF}
LOCAL = "http://localhost"


@dataclass
class ItemRig:
    """A web client, its container and the ledger rig under it."""

    client: TestClient
    container: Container
    ledger: LedgerRig

    def seed(self, *events: Event) -> None:
        self.ledger.events.upsert(list(events))

    def page(self, path: str = "/") -> str:
        response = self.client.get(path)
        assert response.status_code == 200
        return response.text


def make_item_rig(
    ledger: LedgerRig, *, items: bool = True, sync: SyncService | None = None
) -> ItemRig:
    secrets = InMemorySecretStore()
    sync = sync or SyncService({}, secrets, ledger.events, ledger.clock, ledger=ledger.ledger)
    container = Container(
        sync=sync,
        agenda=ledger.agenda,
        settings=SettingsService({}, secrets, sync),
        items=ledger.items if items else None,
    )
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    return ItemRig(TestClient(app, base_url=LOCAL), container, ledger)


def due_soon(item_id: str = "a", *, title: str | None = None, hours: int = 5) -> Event:
    """An open assignment due `hours` after NOW, so it is on Today and in Needs attention."""
    return assignment(item_id, hours=hours, title=title)


def an_event(item_id: str = "e") -> Event:
    return make_event(id=item_id, kind="event", title="Standup", start=NOW + timedelta(hours=1))


def section(html: str, heading_id: str) -> str:
    """The `<section>` whose heading has this id."""
    match = re.search(rf'<section[^>]*aria-labelledby="{heading_id}".*?</section>', html, re.DOTALL)
    assert match is not None, heading_id
    return match.group(0)


def row_of(html: str, item_id: str, ctx: str) -> str:
    """The `<li>` of the item's copy in one list."""
    match = re.search(rf'<li class="row[^"]*" id="row-{ctx}-{item_id}">.*?</li>', html, re.DOTALL)
    assert match is not None, (ctx, item_id)
    return match.group(0)
