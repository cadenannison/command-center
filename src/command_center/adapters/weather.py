"""Weather source: one Open-Meteo forecast Event per day (decision 0045).

The URL is fixed, so the user-URL guard of adapters rule 5 does not apply. Open-Meteo needs no key;
the creds are the user's `latitude` and `longitude`, which are not logged or put in a message.
"""

import math
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from command_center.core.errors import FatalError, SourceError, TransientError
from command_center.core.ports import Clock
from command_center.core.schema import Event, ValidationResult, event_id
from command_center.core.windows import TimeWindow

SOURCE = "weather"
URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 7
CACHE_TTL = timedelta(minutes=20)
TIMEOUT_SECONDS = 10.0
_DAILY = "temperature_2m_max,temperature_2m_min,precipitation_probability_max"
_OK = 200
_TOO_MANY = 429
_SERVER_ERROR = 500
_MAX_LATITUDE = 90.0
_MAX_LONGITUDE = 180.0


class _Daily(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    time: list[date]
    temperature_2m_max: list[float | None]
    temperature_2m_min: list[float | None]
    precipitation_probability_max: list[float | None] = []


class _Forecast(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    timezone: str = "UTC"
    utc_offset_seconds: int = 0
    daily: _Daily


class WeatherAdapter:
    """SourceAdapter for Open-Meteo: a 7-day forecast, cached in memory for 20 minutes."""

    def __init__(self, clock: Clock, *, client: httpx.AsyncClient | None = None) -> None:
        self._clock = clock
        self._client = client
        self._cache: dict[tuple[float, float], tuple[datetime, list[Event]]] = {}

    @property
    def name(self) -> str:
        """The source name stored on every Event: "weather"."""
        return SOURCE

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Check the coordinates and make one request for a single day; never raises."""
        try:
            where = _coordinates(creds)
            _ = await self._request(where, forecast_days=1)
        except SourceError as exc:
            return ValidationResult(ok=False, message=str(exc))
        return ValidationResult(ok=True, message="Connected to Open-Meteo")

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        """Return the forecast days that start in window; a cache hit makes no request."""
        where = _coordinates(creds)
        now = self._clock.now()
        cached = self._cache.get(where)
        if cached is not None and now - cached[0] < CACHE_TTL:
            days = cached[1]
        else:
            days = _events(await self._request(where, forecast_days=FORECAST_DAYS), now)
            self._cache[where] = (now, days)
        return [day for day in days if day.start is not None and window.contains(day.start)]

    async def _request(self, where: tuple[float, float], *, forecast_days: int) -> _Forecast:
        params: dict[str, str | int | float] = {
            "latitude": where[0],
            "longitude": where[1],
            "daily": _DAILY,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
            "forecast_days": forecast_days,
        }
        try:
            if self._client is not None:
                response = await self._client.get(URL, params=params, timeout=TIMEOUT_SECONDS)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    response = await client.get(URL, params=params)
        except httpx.HTTPError:
            msg = "Open-Meteo is unreachable"
            raise TransientError(msg) from None
        return _parse(response)


def _coordinates(creds: Mapping[str, str]) -> tuple[float, float]:
    try:
        latitude, longitude = float(creds["latitude"]), float(creds["longitude"])
    except (KeyError, ValueError):
        msg = "Latitude and longitude must both be numbers"
        raise FatalError(msg) from None
    in_range = abs(latitude) <= _MAX_LATITUDE and abs(longitude) <= _MAX_LONGITUDE
    if not (math.isfinite(latitude) and math.isfinite(longitude) and in_range):
        msg = "Latitude must be within 90 and longitude within 180"
        raise FatalError(msg)
    return latitude, longitude


def _parse(response: httpx.Response) -> _Forecast:
    status = response.status_code
    if status == _TOO_MANY or status >= _SERVER_ERROR:
        msg = f"Open-Meteo is unavailable ({status})"
        raise TransientError(msg)
    if status != _OK:
        msg = f"Open-Meteo rejected the request ({status})"
        raise FatalError(msg)
    try:
        return _Forecast.model_validate_json(response.content)
    except ValidationError:
        msg = "Open-Meteo returned an unexpected response"
        raise FatalError(msg) from None


def _zone(forecast: _Forecast) -> tzinfo:
    try:
        return ZoneInfo(forecast.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(seconds=forecast.utc_offset_seconds))


def _events(forecast: _Forecast, fetched_at: datetime) -> list[Event]:
    zone = _zone(forecast)
    daily = forecast.daily
    events: list[Event] = []
    for index, day in enumerate(daily.time):
        high = _at(daily.temperature_2m_max, index)
        low = _at(daily.temperature_2m_min, index)
        if high is None or low is None:
            continue  # beyond the model's range Open-Meteo sends null; there is nothing to show
        rain = _at(daily.precipitation_probability_max, index)
        title = f"High {round(high)}°, low {round(low)}°"
        if rain is not None:
            title += f", {round(rain)}% rain"
        events.append(
            Event(
                id=event_id(SOURCE, day.isoformat()),
                source=SOURCE,
                kind="weather",
                title=title,
                start=datetime.combine(day, time.min, tzinfo=zone),
                raw={"high_f": high, "low_f": low, "rain_percent": rain},
                fetched_at=fetched_at,
            )
        )
    return events


def _at(values: list[float | None], index: int) -> float | None:
    return values[index] if index < len(values) else None
