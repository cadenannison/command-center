"""The web router over a real ChatService (fake provider, real SQL ledger), for the chat page and
the AI settings card (decisions 0200 to 0203)."""

import re
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chat_support import ChatRig, FakeChatProvider, make_chat_rig
from command_center.services.chat_settings import ChatDefaults
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from command_center.web import create_router
from fakes import InMemorySecretStore
from ledger_support import LedgerRig
from web_items_support import CSRF, HEADERS, LOCAL

TAILNET = "https://mac.tail1234.ts.net"
__all__ = ["HEADERS", "LOCAL", "TAILNET", "WebChatRig", "ai_card", "make_web_chat_rig"]


@dataclass
class WebChatRig:
    client: TestClient
    app: FastAPI
    chat: ChatRig

    def page(self, path: str) -> str:
        response = self.client.get(path)
        assert response.status_code == 200
        return response.text


def make_web_chat_rig(  # noqa: PLR0913
    ledger: LedgerRig,
    provider: FakeChatProvider | None = None,
    *,
    enabled: bool = True,
    defaults: ChatDefaults | None = None,
    with_chat: bool = True,
    limit: int = 10,
) -> WebChatRig:
    chat = make_chat_rig(ledger, provider, enabled=enabled, defaults=defaults, limit=limit)
    secrets = InMemorySecretStore()
    sync = SyncService({}, secrets, ledger.events, ledger.clock, ledger=ledger.ledger)
    container = Container(
        sync=sync,
        agenda=ledger.agenda,
        settings=SettingsService({}, secrets, sync),
        items=ledger.items,
        chat=chat.service if with_chat else None,
    )
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    return WebChatRig(TestClient(app, base_url=LOCAL), app, chat)


def ai_card(html: str) -> str:
    match = re.search(r'<section class="card" id="ai-card".*?</section>', html, flags=re.DOTALL)
    assert match is not None, "no AI settings card"
    return match.group(0)
