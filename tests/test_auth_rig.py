"""make_auth_rig keeps the web rig's item service unless `items=` is passed (decision 0248)."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Engine

import auth_rig
from ledger_support import open_ledger_rig
from sink_support import open_engine
from web_rig import WebRig, make_rig


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    yield from open_engine("sqlite", tmp_path)  # the generator disposes the engine afterwards


@pytest.fixture
def other_engine(tmp_path: Path) -> Iterator[Engine]:
    (tmp_path / "other").mkdir()
    yield from open_engine("sqlite", tmp_path / "other")


@pytest.fixture
def web_rig_with_items(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> object:
    """make_rig is patched to return a web rig that already has an item service."""
    kept = open_ledger_rig(engine).items

    def with_items(*args: object, **kwargs: object) -> WebRig:
        base = make_rig(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        return replace(base, container=replace(base.container, items=kept))

    monkeypatch.setattr(auth_rig, "make_rig", with_items)
    return kept


def test_leaving_items_out_keeps_the_web_rigs_item_service(web_rig_with_items: object) -> None:
    assert auth_rig.make_auth_rig().container.items is web_rig_with_items


def test_passing_none_removes_the_item_service(web_rig_with_items: object) -> None:
    assert web_rig_with_items is not None

    assert auth_rig.make_auth_rig(items=None).container.items is None


def test_passing_a_service_replaces_the_web_rigs(
    other_engine: Engine, web_rig_with_items: object
) -> None:
    other = open_ledger_rig(other_engine).items

    assert auth_rig.make_auth_rig(items=other).container.items is other
    assert other is not web_rig_with_items
