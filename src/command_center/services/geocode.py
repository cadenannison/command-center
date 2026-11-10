"""City search for the weather form: a rate limit and redacted failures around a Geocoder (0180)."""

import logging
import math
from collections import deque
from datetime import datetime, timedelta

from command_center.core.errors import FatalError, TransientError
from command_center.core.geocode import (
    MAX_CANDIDATES,
    MIN_QUERY_LENGTH,
    GeocodeCandidate,
    normalise_query,
)
from command_center.core.ports import Clock, Geocoder
from command_center.services.errors import (
    GeocodeRateLimitedError,
    GeocodeUnavailableError,
    error_text,
    safe_message,
)

SEARCH_LIMIT = 10
SEARCH_WINDOW = timedelta(seconds=60)

logger = logging.getLogger(__name__)


class GeocodeService:
    """Searches for places by name, at most `limit` times per `window` across every caller.

    The limit is global, like the pairing lock: every request reaches the api from 127.0.0.1, so
    there is no caller to tell apart. A search that fails still counts, and nothing in a log line,
    an exception or a result carries the query text.
    """

    def __init__(
        self,
        geocoder: Geocoder,
        clock: Clock,
        *,
        limit: int = SEARCH_LIMIT,
        window: timedelta = SEARCH_WINDOW,
    ) -> None:
        self._geocoder = geocoder
        self._clock = clock
        self._limit = limit
        self._window = window
        self._recent: deque[datetime] = deque()

    async def search(self, query: str) -> list[GeocodeCandidate]:
        """Up to MAX_CANDIDATES places for query; a query too short to search for gives [].

        Raises GeocodeRateLimitedError over the limit and GeocodeUnavailableError when the
        provider fails.
        """
        text = normalise_query(query)
        if len(text) < MIN_QUERY_LENGTH:
            return []
        self._admit()
        try:
            found = await self._geocoder.search(text)
        except (TransientError, FatalError) as exc:
            logger.warning(
                "city search failed: %s",
                type(exc).__name__,
                extra={"reason": "geocode_failed", "error_class": type(exc).__name__},
            )
            message = f"City search failed: {error_text(exc)}"
            raise GeocodeUnavailableError(safe_message(message)) from None
        return found[:MAX_CANDIDATES]

    def _admit(self) -> None:
        # No await between the check and the append, so two searches cannot share the last slot.
        now = self._clock.now()
        while self._recent and now - self._recent[0] >= self._window:
            _ = self._recent.popleft()
        if len(self._recent) >= self._limit:
            wait = (self._recent[0] + self._window - now).total_seconds()
            logger.warning("city search refused", extra={"reason": "geocode_rate_limited"})
            raise GeocodeRateLimitedError(max(1, math.ceil(wait)))
        self._recent.append(now)
