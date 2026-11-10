"""The History page: what was completed on a day, and what left its source (decision 0153)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta, tzinfo
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from command_center.core.ledger import LOCAL_SOURCE, HistoryDay, LedgerEntry
from command_center.services.container import Container
from command_center.web.render import Renderer
from command_center.web.views import safe_link

NO_ITEMS = "Items are not enabled"
_GROUPS = (
    ("done_by_you", "Completed by you", "Nothing you checked off on this day."),
    ("done_by_source", "Completed at the source", "Nothing the sources reported done on this day."),
    ("gone", "Disappeared from its source", "Nothing left its source on this day."),
)

DayParam = Annotated[date | None, Query(alias="date")]


@dataclass(frozen=True)
class HistoryLine:
    """One entry as the page draws it."""

    at: str
    source: str
    title: str
    link: str | None
    note: str | None
    reopened: bool


@dataclass(frozen=True)
class HistorySection:
    """One group of the day."""

    key: str
    heading: str
    empty: str
    lines: tuple[HistoryLine, ...]


@dataclass(frozen=True)
class HistoryView:
    """The History page for one day."""

    day: date
    title: str
    sections: tuple[HistorySection, ...]
    previous: date
    next: date


def source_label(source: str) -> str:
    """A readable source name; the user's own tasks read "You"."""
    return "You" if source == LOCAL_SOURCE else source.replace("_", " ")


def history_line(entry: LedgerEntry, tz: tzinfo) -> HistoryLine:
    """One entry; the time is in the settings timezone."""
    return HistoryLine(
        at=f"{entry.at.astimezone(tz):%H:%M}",
        source=source_label(entry.source),
        title=entry.title,
        link=safe_link(entry.link),
        note=entry.note,
        reopened=entry.reopened,
    )


def history_view(day: date, found: HistoryDay | None, tz: tzinfo) -> HistoryView:
    """The page for day; `found` is None when nothing happened on it."""
    sections = tuple(
        HistorySection(
            key=key,
            heading=heading,
            empty=empty,
            lines=tuple(history_line(e, tz) for e in (getattr(found, key) if found else ())),
        )
        for key, heading, empty in _GROUPS
    )
    one_day = timedelta(days=1)
    return HistoryView(
        day, f"History: {day:%a} {day.day} {day:%b %Y}", sections, day - one_day, day + one_day
    )


def history_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """`GET /history?date=`; 404 while the container has no item service."""
    router = APIRouter()

    @router.get("/history", response_class=HTMLResponse)
    async def history_page(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
    ) -> HTMLResponse:
        if services.items is None:
            raise HTTPException(status_code=404, detail=NO_ITEMS)
        shown = day or services.agenda.today()
        days = await services.items.history(shown, shown)
        view = history_view(shown, days[0] if days else None, services.agenda.tz)
        return renderer.render(request, "history.html", {"active": "history", "view": view})

    return router
