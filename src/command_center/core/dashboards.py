"""Dashboards and display settings: the shapes the server stores and the pure rules they obey.

The layout document is the UI's layout (decision 0331) as the server accepts it: version 1, known
keys only, integer geometry, ids matched by pattern, at most 50 items and 64 KB. The server stores
what passes; the UI's sanitizer stays authoritative on read (decision 0355). Every refusal uses a
fixed text, so a stored or submitted value is never echoed (decision 0023).
"""

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

LAYOUT_VERSION = 1
MAX_LAYOUT_BYTES = 64 * 1024
MAX_LAYOUT_ITEMS = 50
GRID_COLUMNS = 12
MAX_ROW = 500
MAX_HEIGHT = 64
MAX_ITEM_SOURCES = 12
MAX_OPTIONS = 20
MAX_OPTION_INT = 1_000_000
MAX_DASHBOARDS = 20
MAX_NAME = 60
MAX_SOURCE_COLORS = 16
GLOW_MAX = 1.6
TEXT_SCALE_MIN = 90
TEXT_SCALE_MAX = 150

# Ids are persisted and permanent; the pattern is the UI's own (ui/src/layout/validate.ts).
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
SOURCE_PATTERN = r"^[a-z][a-z0-9_]{0,15}$"
OPTION_KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,39}$"

# The eight colors a source may be given (docs/design/spec.md, decision 0343).
ColorId = Literal["violet", "rose", "teal", "amber", "sky", "silver", "green", "pink"]
ThemeChoice = Literal["light", "dark", "system"]
Density = Literal["comfortable", "compact"]

_STRICT = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

_NAME_CODE = "dashboard_name"
_NAME_MSG = "name must be 1 to 60 characters with no control characters"
_ITEMS_CODE = "layout_items"
_DUPLICATE_MSG = "layout item ids must be unique"
_BOUNDS_CODE = "layout_bounds"
_BOUNDS_MSG = "a layout item must fit in 12 columns"
_SIZE_CODE = "layout_size"
_SIZE_MSG = "layout must be at most 65536 bytes"
_SOURCES_CODE = "layout_sources"
_SOURCES_MSG = "an item's sources must be unique"

_ID = Annotated[str, Field(pattern=ID_PATTERN)]
_SOURCE = Annotated[str, Field(pattern=SOURCE_PATTERN)]
_OPTION_VALUE = StrictBool | Annotated[StrictInt, Field(ge=-MAX_OPTION_INT, le=MAX_OPTION_INT)]


class LayoutItem(BaseModel):
    """One placed widget, in the UI's own keys (`ui/src/layout/types.ts`)."""

    model_config = _STRICT

    id: _ID
    widget_id: _ID = Field(alias="widgetId")
    x: Annotated[StrictInt, Field(ge=0, lt=GRID_COLUMNS)]
    y: Annotated[StrictInt, Field(ge=0, lt=MAX_ROW)]
    w: Annotated[StrictInt, Field(ge=1, le=GRID_COLUMNS)]
    h: Annotated[StrictInt, Field(ge=1, le=MAX_HEIGHT)]
    pinned: StrictBool
    sources: Annotated[list[_SOURCE], Field(max_length=MAX_ITEM_SOURCES)]
    options: Annotated[
        dict[Annotated[str, Field(pattern=OPTION_KEY_PATTERN)], _OPTION_VALUE],
        Field(max_length=MAX_OPTIONS),
    ]

    @model_validator(mode="after")
    def _fits(self) -> "LayoutItem":
        if self.x + self.w > GRID_COLUMNS:
            raise PydanticCustomError(_BOUNDS_CODE, _BOUNDS_MSG)
        if len(set(self.sources)) != len(self.sources):
            raise PydanticCustomError(_SOURCES_CODE, _SOURCES_MSG)
        return self


class Layout(BaseModel):
    """The layout document: version 1 and its items."""

    model_config = _STRICT

    version: Annotated[StrictInt, Field(ge=LAYOUT_VERSION, le=LAYOUT_VERSION)]
    items: Annotated[list[LayoutItem], Field(max_length=MAX_LAYOUT_ITEMS)]

    @model_validator(mode="after")
    def _checked(self) -> "Layout":
        if len({item.id for item in self.items}) != len(self.items):
            raise PydanticCustomError(_ITEMS_CODE, _DUPLICATE_MSG)
        if layout_size(self) > MAX_LAYOUT_BYTES:
            raise PydanticCustomError(_SIZE_CODE, _SIZE_MSG)
        return self


def layout_size(layout: Layout) -> int:
    """The size in bytes of the layout as it is stored (compact JSON, the UI's keys)."""
    return len(layout_json(layout).encode("utf-8"))


def layout_json(layout: Layout) -> str:
    """The layout as the compact JSON text that is stored."""
    return json.dumps(
        layout.model_dump(mode="json", by_alias=True), separators=(",", ":"), ensure_ascii=True
    )


def parse_layout(text: str) -> Layout:
    """Parse stored layout JSON; raises `pydantic.ValidationError` for anything that fails."""
    return Layout.model_validate_json(text, strict=True)


def clean_name(value: str) -> str:
    """Trim a dashboard name; 1 to 60 characters and no control characters."""
    name = value.strip()
    if not 1 <= len(name) <= MAX_NAME or any(not ch.isprintable() for ch in name):
        raise PydanticCustomError(_NAME_CODE, _NAME_MSG)
    return name


class DashboardInput(BaseModel):
    """What a client sends to create a dashboard or replace one."""

    model_config = _STRICT

    name: str
    layout: Layout

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return clean_name(value)


class Dashboard(BaseModel):
    """A stored dashboard. `revision` starts at 1 and rises by one on every replace."""

    model_config = _STRICT

    id: str
    name: str
    position: int
    layout: Layout
    revision: int
    updated_at: AwareDatetime


class ReorderInput(BaseModel):
    """The dashboards' ids in the order wanted; it must name every dashboard exactly once."""

    model_config = _STRICT

    ids: Annotated[list[_ID], Field(max_length=MAX_DASHBOARDS)]


class DisplayInput(BaseModel):
    """The display settings a client sends. Nothing about an AI provider or a secret lives here."""

    model_config = _STRICT

    theme: ThemeChoice = "system"
    high_contrast: StrictBool = False
    density: Density = "comfortable"
    glow: Annotated[StrictFloat | StrictInt, Field(ge=0, le=GLOW_MAX, allow_inf_nan=False)] = 1.0
    text_scale: Annotated[StrictInt, Field(ge=TEXT_SCALE_MIN, le=TEXT_SCALE_MAX)] = 100
    privacy_mode: StrictBool = False
    source_colors: Annotated[
        dict[_SOURCE, ColorId],
        Field(max_length=MAX_SOURCE_COLORS),
    ] = Field(default_factory=dict)
    owed_replies_as_tasks: StrictBool = False


class DisplaySettings(DisplayInput):
    """Stored display settings. Revision 0 means nothing has been saved yet (the defaults)."""

    revision: int = 0
    updated_at: datetime | None = None


class RevisionConflictError(Exception):
    """The revision the caller sent is not the stored one: another writer got there first."""


class DashboardNotFoundError(Exception):
    """No dashboard has this id."""


class DashboardLimitError(Exception):
    """There are already `MAX_DASHBOARDS` dashboards."""


class DashboardSetError(Exception):
    """A reorder did not name exactly the stored dashboards: the caller's list is stale."""
