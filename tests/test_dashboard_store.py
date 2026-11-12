"""DashboardStore and DisplaySettingsStore on SQLite (Postgres with CC_TEST_POSTGRES_URL)."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from builders import NOW
from command_center.core.dashboards import (
    MAX_DASHBOARDS,
    DashboardLimitError,
    DashboardNotFoundError,
    DashboardSetError,
    DisplayInput,
    DisplaySettings,
    Layout,
    RevisionConflictError,
)
from command_center.storage.sqlite_dashboards import (
    SqliteDashboardStore,
    SqliteDisplaySettingsStore,
    ensure_dashboard_schema,
)
from dashboard_support import DISPLAY, item, layout_doc
from sink_support import DATABASES, open_engine

Stores = tuple[SqliteDashboardStore, SqliteDisplaySettingsStore]
LAYOUT = Layout.model_validate(layout_doc())
OTHER = Layout.model_validate(layout_doc(item(id="w2", widgetId="events")))


@pytest.fixture(params=DATABASES)
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Stores]:
    for engine in open_engine(request.param, tmp_path):
        ensure_dashboard_schema(engine)
        yield SqliteDashboardStore(engine), SqliteDisplaySettingsStore(engine)


def test_a_created_dashboard_is_last_at_revision_one(stores: Stores) -> None:
    dashboards, _ = stores
    first = dashboards.add("a", "One", LAYOUT, NOW)
    second = dashboards.add("b", "Two", OTHER, NOW)
    assert (first.revision, first.position, second.position) == (1, 0, 1)
    assert [d.id for d in dashboards.list_all()] == ["a", "b"]
    assert dashboards.get("b") == second
    assert dashboards.get("nope") is None
    assert second.layout == OTHER
    assert second.updated_at == NOW


def test_replace_raises_the_revision_and_keeps_position(stores: Stores) -> None:
    dashboards, _ = stores
    dashboards.add("a", "One", LAYOUT, NOW)
    later = NOW + timedelta(minutes=5)
    saved = dashboards.replace("a", 1, "Renamed", OTHER, later)
    assert (saved.revision, saved.name, saved.layout, saved.updated_at) == (
        2,
        "Renamed",
        OTHER,
        later,
    )
    assert saved.position == 0


def test_a_stale_replace_changes_nothing(stores: Stores) -> None:
    dashboards, _ = stores
    dashboards.add("a", "One", LAYOUT, NOW)
    dashboards.replace("a", 1, "Mine", OTHER, NOW)
    with pytest.raises(RevisionConflictError):
        dashboards.replace("a", 1, "Theirs", LAYOUT, NOW)
    kept = dashboards.get("a")
    assert kept is not None
    assert (kept.name, kept.revision) == ("Mine", 2)


def test_replace_and_delete_of_an_unknown_id_are_not_found(stores: Stores) -> None:
    dashboards, _ = stores
    with pytest.raises(DashboardNotFoundError):
        dashboards.replace("nope", 1, "x", LAYOUT, NOW)
    with pytest.raises(DashboardNotFoundError):
        dashboards.delete("nope", 1)


def test_delete_needs_the_current_revision(stores: Stores) -> None:
    dashboards, _ = stores
    dashboards.add("a", "One", LAYOUT, NOW)
    with pytest.raises(RevisionConflictError):
        dashboards.delete("a", 2)
    dashboards.delete("a", 1)
    assert dashboards.list_all() == []


def test_reorder_sets_positions_and_needs_the_exact_set(stores: Stores) -> None:
    dashboards, _ = stores
    for name in ("a", "b", "c"):
        dashboards.add(name, name, LAYOUT, NOW)
    reordered = dashboards.reorder(["c", "a", "b"])
    assert [d.id for d in reordered] == ["c", "a", "b"]
    assert [d.id for d in dashboards.list_all()] == ["c", "a", "b"]
    for bad in (["a", "b"], ["a", "b", "c", "d"], ["a", "a", "b"]):
        with pytest.raises(DashboardSetError):
            dashboards.reorder(bad)
    assert [d.id for d in dashboards.list_all()] == ["c", "a", "b"]


def test_the_dashboard_count_is_capped(stores: Stores) -> None:
    dashboards, _ = stores
    for n in range(MAX_DASHBOARDS):
        dashboards.add(f"d{n}", "x", LAYOUT, NOW)
    with pytest.raises(DashboardLimitError):
        dashboards.add("extra", "x", LAYOUT, NOW)


def test_users_do_not_see_each_others_dashboards(stores: Stores) -> None:
    dashboards, _ = stores
    dashboards.add("a", "One", LAYOUT, NOW, user_id="alice")
    assert dashboards.list_all() == []
    assert dashboards.get("a") is None


def test_display_settings_default_to_revision_zero(stores: Stores) -> None:
    _, display = stores
    assert display.get() == DisplaySettings()
    assert display.get().revision == 0


def test_display_settings_round_trip_and_version(stores: Stores) -> None:
    _, display = stores
    body = DisplaySettings(**DisplayInput.model_validate(DISPLAY).model_dump())
    first = display.replace(body, 0, NOW)
    assert (first.revision, first.theme, first.updated_at) == (1, "dark", NOW)
    assert first.source_colors == {"cal": "violet", "canvas": "rose"}
    second = display.replace(body.model_copy(update={"theme": "light"}), 1, NOW)
    assert (second.revision, second.theme) == (2, "light")


def test_a_stale_display_write_changes_nothing(stores: Stores) -> None:
    _, display = stores
    display.replace(DisplaySettings(theme="dark"), 0, NOW)
    for stale in (0, 2):
        with pytest.raises(RevisionConflictError):
            display.replace(DisplaySettings(theme="light"), stale, NOW)
    assert display.get().theme == "dark"


def test_adding_a_duplicate_id_is_a_conflict(stores: Stores) -> None:
    dashboards, _ = stores
    dashboards.add("a", "One", LAYOUT, NOW)
    with pytest.raises(RevisionConflictError):
        dashboards.add("a", "Two", LAYOUT, NOW)
    assert [d.name for d in dashboards.list_all()] == ["One"]
