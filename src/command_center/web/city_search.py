"""The weather card's "Find a city" box: search and fill, both actions of PUT /settings/weather.

Neither action stores anything. `search` lists up to five places and picks none; `fill` puts the
coordinates of the place the user chose into the two editable inputs, and only Connect stores them
(decision 0183). The typed text travels in the PUT body, never in a URL, and nothing here logs it.
"""

import math
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import HTMLResponse

from command_center.core.geocode import (
    MAX_QUERY_LENGTH,
    MIN_QUERY_LENGTH,
    GeocodeCandidate,
    normalise_query,
)
from command_center.services.container import Container
from command_center.services.errors import GeocodeRateLimitedError, GeocodeUnavailableError
from command_center.services.models import SourceSettings
from command_center.web.cards import card_view
from command_center.web.render import Renderer

CITY_ACTIONS = frozenset({"search", "fill"})

NOT_AVAILABLE = "City search is not available here. Enter the latitude and longitude yourself."
TOO_SHORT = f"Type at least {MIN_QUERY_LENGTH} characters of a city name."
TOO_LONG = f"A city name is at most {MAX_QUERY_LENGTH} characters."
NO_MATCH = "No places matched. Check the spelling, or try just the city name."
BAD_COORDINATES = "Those coordinates are not valid. Search again and pick a place from the list."
NO_LABEL = "the latitude and longitude"
NOT_SAVED = "Nothing is saved until you press Connect."
_MAX_LABEL = 120
_LATITUDE_LIMIT = 90
_LONGITUDE_LIMIT = 180


@dataclass(frozen=True)
class PlaceView:
    """One candidate as the page shows it, with what its Use button sends."""

    label: str
    detail: str
    vals: dict[str, str]


def _decimal(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def place_view(place: GeocodeCandidate) -> PlaceView:
    """The list row of a candidate: name, then region and country, then the population if known."""
    where = ", ".join(part for part in (place.region, place.country) if part)
    parts = [where] if where else []
    if place.population is not None:
        parts.append(f"population {place.population:,}")
    label = ", ".join(part for part in (place.name, place.region, place.country) if part)
    vals = {
        "action": "fill",
        "latitude": _decimal(place.latitude),
        "longitude": _decimal(place.longitude),
        "label": label[:_MAX_LABEL],
    }
    return PlaceView(place.name, " · ".join(parts), vals)


def _coordinate(raw: object, limit: int) -> str | None:
    """The cleaned text of a coordinate in [-limit, limit], or None for anything else."""
    if not isinstance(raw, str):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return _decimal(value) if math.isfinite(value) and abs(value) <= limit else None


def _query_problem(text: str) -> str | None:
    """Why text cannot be searched for, or None."""
    if len(text) < MIN_QUERY_LENGTH:
        return TOO_SHORT
    return TOO_LONG if len(text) > MAX_QUERY_LENGTH else None


class CitySearch:
    """Runs the `search` and `fill` actions and renders their fragments."""

    def __init__(self, renderer: Renderer) -> None:
        self._renderer = renderer

    async def run(
        self,
        request: Request,
        services: Container,
        item: SourceSettings,
        action: str,
        form: dict[str, object],
    ) -> HTMLResponse:
        """Do the action; the answer is the HTML that goes under the search box."""
        if action == "fill":
            return self._fill(request, item, form)
        return await self._search(request, services, item.source, form.get("city"))

    async def _search(
        self, request: Request, services: Container, source: str, raw: object
    ) -> HTMLResponse:
        geocode = services.geocode
        if geocode is None:
            return self._say(request, source, NOT_AVAILABLE)
        text = normalise_query(raw) if isinstance(raw, str) else ""
        problem = _query_problem(text)
        if problem is not None:
            return self._say(request, source, problem)
        try:
            found = await geocode.search(text)
        except GeocodeRateLimitedError as exc:
            wait = f"Wait {exc.retry_after_seconds} seconds, then search again."
            return self._say(request, source, f"Too many searches in the last minute. {wait}")
        except GeocodeUnavailableError as exc:
            return self._say(request, source, str(exc))
        if not found:
            return self._say(request, source, NO_MATCH, ok=True)
        places = [place_view(place) for place in found]
        return self._renderer.render(
            request, "_city_results.html", {"source": source, "places": places}
        )

    def _fill(
        self, request: Request, item: SourceSettings, form: dict[str, object]
    ) -> HTMLResponse:
        latitude = _coordinate(form.get("latitude"), _LATITUDE_LIMIT)
        longitude = _coordinate(form.get("longitude"), _LONGITUDE_LIMIT)
        if latitude is None or longitude is None:
            return self._say(request, item.source, BAD_COORDINATES)
        label = form.get("label")
        named = label[:_MAX_LABEL] if isinstance(label, str) and label else NO_LABEL
        card = card_view(item, typed={"latitude": latitude, "longitude": longitude})
        context = {
            "source": item.source,
            "message": f"Filled in {named}. {NOT_SAVED}",
            "ok": True,
            "card": card,
        }
        return self._renderer.render(request, "_city_results.html", context)

    def _say(
        self, request: Request, source: str, message: str, *, ok: bool = False
    ) -> HTMLResponse:
        context = {"source": source, "message": message, "ok": ok}
        return self._renderer.render(request, "_city_results.html", context)
