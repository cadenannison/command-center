"""Builders for dashboard tests: a valid layout and display body, parsed through the real models."""

import copy
from typing import Any

ITEM: dict[str, Any] = {
    "id": "w1",
    "widgetId": "tasks",
    "x": 0,
    "y": 0,
    "w": 4,
    "h": 8,
    "pinned": False,
    "sources": ["canvas", "ls"],
    "options": {"compact": True},
}


def layout_doc(*items: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "items": [copy.deepcopy(i) for i in (items or (ITEM,))]}


def item(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    return {**copy.deepcopy(ITEM), **changes}


def dashboard_body(name: str = "Main", layout: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "layout": layout or layout_doc()}


DISPLAY: dict[str, Any] = {
    "theme": "dark",
    "high_contrast": True,
    "density": "compact",
    "glow": 1.6,
    "text_scale": 150,
    "privacy_mode": True,
    "source_colors": {"cal": "violet", "canvas": "rose"},
    "owed_replies_as_tasks": True,
}


class SeqIds:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"d{self._n}"
