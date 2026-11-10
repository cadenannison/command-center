"""City search over Open-Meteo's geocoding API (decision 0180).

The URL is fixed and public, so the user-URL guard of adapters rule 5 does not apply. The query
text is the user's own typing: it is sent to Open-Meteo and nowhere else, never put in an error
message, and kept out of httpx's own request log line (`_QuietRequestLog`).
"""

import logging

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from command_center.adapters.http_cap import ReplyTooLarge, read_capped
from command_center.core.errors import FatalError, TransientError
from command_center.core.geocode import MAX_CANDIDATES, GeocodeCandidate

URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_SECONDS = 10.0
_OK = 200
_TOO_MANY = 429
_SERVER_ERROR = 500


class _QuietRequestLog(logging.Filter):
    """Drops httpx's INFO line for a geocoding request: it prints the whole URL, query included."""

    def filter(self, record: logging.LogRecord) -> bool:
        return URL not in record.getMessage()


def _quiet_httpx_request_log() -> None:
    httpx_logger = logging.getLogger("httpx")
    if not any(isinstance(item, _QuietRequestLog) for item in httpx_logger.filters):
        httpx_logger.addFilter(_QuietRequestLog())


_quiet_httpx_request_log()


class _Hit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    latitude: float
    longitude: float
    admin1: str | None = None
    country: str | None = None
    population: int | None = None


class _Reply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    results: list[_Hit] = []  # Open-Meteo leaves the key out when nothing matched


class OpenMeteoGeocoder:
    """Geocoder for Open-Meteo: up to five places per query, in Open-Meteo's own order."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search(self, query: str) -> list[GeocodeCandidate]:
        """Return the candidates for query; no match is []. Failures carry no query text."""
        params: dict[str, str | int] = {
            "name": query,
            "count": MAX_CANDIDATES,
            "language": "en",
            "format": "json",
        }
        try:
            if self._client is not None:
                raw = await self._fetch(self._client, params)
            else:
                # trust_env=False: a proxy in the environment must not see the typed city (0246).
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, trust_env=False) as client:
                    raw = await self._fetch(client, params)
        except httpx.HTTPError:
            msg = "Open-Meteo city search is unreachable"
            raise TransientError(msg) from None
        return _candidates(_parse(raw))

    @staticmethod
    async def _fetch(client: httpx.AsyncClient, params: dict[str, str | int]) -> bytes:
        """The reply body, read as a stream and capped (the cap is shared with chat, 0246).

        The status is decided before the body is read, so an error page is never buffered.
        """
        try:
            async with client.stream(
                "GET", URL, params=params, timeout=TIMEOUT_SECONDS
            ) as response:
                _check_status(response.status_code)
                return await read_capped(response)
        except ReplyTooLarge:
            msg = "Open-Meteo city search sent a reply that is too large"
            raise FatalError(msg) from None
        except httpx.DecodingError:  # a body that does not match its content-encoding
            msg = "Open-Meteo city search returned an unexpected response"
            raise FatalError(msg) from None


def _check_status(status: int) -> None:
    if status == _TOO_MANY or status >= _SERVER_ERROR:
        msg = f"Open-Meteo city search is unavailable ({status})"
        raise TransientError(msg)
    if status != _OK:
        msg = f"Open-Meteo rejected the city search ({status})"
        raise FatalError(msg)


def _parse(raw: bytes) -> _Reply:
    try:
        return _Reply.model_validate_json(raw)
    except ValidationError:
        msg = "Open-Meteo city search returned an unexpected response"
        raise FatalError(msg) from None


def _candidates(reply: _Reply) -> list[GeocodeCandidate]:
    try:
        return [
            GeocodeCandidate(
                name=hit.name,
                region=hit.admin1,
                country=hit.country,
                latitude=hit.latitude,
                longitude=hit.longitude,
                population=hit.population,
            )
            for hit in reply.results[:MAX_CANDIDATES]
        ]
    except ValidationError:  # a coordinate outside the globe, or a negative population
        msg = "Open-Meteo city search returned an unexpected response"
        raise FatalError(msg) from None
