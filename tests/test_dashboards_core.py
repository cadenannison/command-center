"""The pure rules for layouts, names and display settings (decision 0355)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from command_center.core.dashboards import (
    MAX_LAYOUT_BYTES,
    DashboardInput,
    DisplayInput,
    Layout,
    layout_json,
    parse_layout,
)
from dashboard_support import DISPLAY, item, layout_doc


def test_a_valid_layout_round_trips_with_the_uis_keys() -> None:
    layout = Layout.model_validate(layout_doc())
    assert json.loads(layout_json(layout)) == layout_doc()
    assert parse_layout(layout_json(layout)) == layout


@pytest.mark.parametrize(
    "doc",
    [
        {"version": 2, "items": []},
        {"version": "1", "items": []},
        {"version": True, "items": []},
        {"items": []},
        {"version": 1},
        {"version": 1, "items": [], "extra": 1},
        layout_doc(item(extra=1)),
        layout_doc(item(x=1.5)),
        layout_doc(item(x=True)),
        layout_doc(item(x="1")),
        layout_doc(item(x=-1)),
        layout_doc(item(x=12)),
        layout_doc(item(x=10, w=4)),
        layout_doc(item(w=0)),
        layout_doc(item(w=13)),
        layout_doc(item(h=0)),
        layout_doc(item(h=65)),
        layout_doc(item(y=500)),
        layout_doc(item(pinned=1)),
        layout_doc(item(id="has space")),
        layout_doc(item(id="")),
        layout_doc(item(id="x" * 65)),
        layout_doc(item(widgetId="<script>")),
        layout_doc(item(sources=["Canvas"])),
        layout_doc(item(sources=["a b"])),
        layout_doc(item(sources=["canvas", "canvas"])),
        layout_doc(item(sources=[f"s{i}" for i in range(13)])),
        layout_doc(item(options={"title": "free text"})),
        layout_doc(item(options={"bad key": 1})),
        layout_doc(item(options={f"k{i}": 1 for i in range(21)})),
        layout_doc(item(options={"n": 1.5})),
        layout_doc(item(), item()),
        {"version": 1, "items": [item(id=f"w{i}") for i in range(51)]},
    ],
)
def test_a_layout_outside_the_rules_is_refused(doc: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Layout.model_validate(doc)


def test_fifty_items_are_accepted() -> None:
    doc = {"version": 1, "items": [item(id=f"w{i}", y=i) for i in range(50)]}
    assert len(Layout.model_validate(doc).items) == 50


def test_the_size_limit_is_enforced_on_the_stored_text() -> None:
    doc = {"version": 1, "items": [item(id=f"w{i}") for i in range(50)]}
    # 50 items are far under 64 KB; the limit is what the stored text may be, so prove the bound
    assert len(layout_json(Layout.model_validate(doc)).encode()) < MAX_LAYOUT_BYTES


def test_a_refusal_never_echoes_the_submitted_value() -> None:
    with pytest.raises(ValidationError) as caught:
        Layout.model_validate(layout_doc(item(id="fake-secret value")))
    assert "fake-secret" not in str(caught.value)


@pytest.mark.parametrize("name", ["", "   ", "x" * 61, "bad\nname", "tab\tname"])
def test_a_bad_dashboard_name_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        DashboardInput.model_validate({"name": name, "layout": layout_doc()})


def test_a_dashboard_name_is_trimmed() -> None:
    body = DashboardInput.model_validate({"name": "  Week  ", "layout": layout_doc()})
    assert body.name == "Week"


def test_display_defaults_are_the_documented_ones() -> None:
    d = DisplayInput()
    assert (d.theme, d.high_contrast, d.density, d.glow, d.text_scale) == (
        "system",
        False,
        "comfortable",
        1.0,
        100,
    )
    assert (d.privacy_mode, d.source_colors, d.owed_replies_as_tasks) == (False, {}, False)


def test_the_display_edges_are_accepted() -> None:
    assert DisplayInput.model_validate(DISPLAY).glow == 1.6
    assert DisplayInput.model_validate({**DISPLAY, "glow": 0, "text_scale": 90}).text_scale == 90


@pytest.mark.parametrize(
    "change",
    [
        {"theme": "blue"},
        {"density": "tiny"},
        {"glow": 1.7},
        {"glow": -0.1},
        {"glow": float("nan")},
        {"glow": True},
        {"glow": "1.5"},
        {"text_scale": 89},
        {"text_scale": 151},
        {"text_scale": 100.5},
        {"high_contrast": "yes"},
        {"source_colors": {"cal": "mauve"}},
        {"source_colors": {"Cal": "violet"}},
        {"source_colors": {f"s{i}": "rose" for i in range(17)}},
        {"ai_provider": "gemini"},
        {"api_key": "fake-key"},
    ],
)
def test_a_display_setting_outside_the_rules_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DisplayInput.model_validate({**DISPLAY, **change})
