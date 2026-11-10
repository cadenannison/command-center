"""The web item flow over the real composition root, in single and distributed mode (0074)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_center.app import build_container
from command_center.config import Settings
from command_center.web import create_router

CSRF = "fake-csrf-token-for-tests"
HEADERS = {"X-CSRF-Token": CSRF}
FAKE_REDIS = "redis://:fake-hunter2pw@127.0.0.1:1/0"  # nothing listens: the tests never connect


def make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, distributed: bool
) -> TestClient:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'items.db'}")
    monkeypatch.setenv("CC_TZ", "America/Denver")
    if distributed:
        monkeypatch.setenv("CC_MODE", "distributed")
        monkeypatch.setenv("CC_REDIS_URL", FAKE_REDIS)
    container = build_container(Settings(_env_file=None))  # type: ignore[call-arg]
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    return TestClient(app, base_url="http://localhost")


@pytest.mark.parametrize("distributed", [False, True], ids=["single", "distributed"])
def test_a_task_made_in_the_web_ui_can_be_checked_off_and_is_in_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, distributed: bool
) -> None:
    client = make_client(monkeypatch, tmp_path, distributed=distributed)
    day = client.get("/").text.split('name="due_date" type="date" value="')[1][:10]
    form = {"title": "Fake task", "due_date": day, "due_time": "23:59", "label": ""}

    created = client.post("/tasks", data=form, headers=HEADERS)
    page = client.get(f"/?date={day}").text
    item_id = page.split('id="row-agenda-')[1].split('"')[0]
    client.post(f"/items/{item_id}/done?ctx=agenda&day={day}", headers=HEADERS)
    history = client.get("/history").text

    assert created.headers["hx-redirect"] == f"/?date={day}"
    assert "Fake task" in page
    assert "Fake task" in history.split('id="h-done_by_you"')[1].split("</section>")[0]
