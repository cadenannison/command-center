"""iCloud calendars over CalDAV with an app-specific password (the only importer of `caldav`)."""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, tzinfo
from typing import Protocol, cast

from caldav.collection import Calendar
from caldav.davclient import DAVClient
from caldav.lib.error import AuthorizationError, DAVError

from command_center.adapters.ical_events import EXPANSION_PAD, events_in_window, parse_calendar
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.ports import Clock
from command_center.core.schema import Event, ValidationResult
from command_center.core.windows import TimeWindow

SOURCE_NAME = "apple_calendar"
ICLOUD_URL = "https://caldav.icloud.com/"
TIMEOUT_SECONDS = 10


class CalendarHandle(Protocol):
    """One calendar on the server: a stable key, a display name and its items as iCalendar text."""

    @property
    def key(self) -> str: ...

    @property
    def label(self) -> str: ...

    def event_data(self, start: datetime, end: datetime) -> Sequence[str]:
        """Return each VEVENT object overlapping [start, end), recurrences expanded."""
        ...


class Session(Protocol):
    """A logged-in CalDAV connection. Blocking; callers run it in a worker thread."""

    def calendars(self) -> Sequence[CalendarHandle]: ...

    def close(self) -> None: ...


type SessionFactory = Callable[[str, str], Session]


class _Resource(Protocol):
    @property
    def data(self) -> object: ...


class _Searchable(Protocol):
    def search(
        self, *, start: datetime, end: datetime, event: bool, expand: bool
    ) -> Sequence[_Resource]: ...


class _Principal(Protocol):
    def get_calendars(self) -> Sequence[Calendar]: ...


class _Client(Protocol):
    def principal(self) -> _Principal: ...

    def close(self) -> None: ...


class _CaldavCalendar:
    def __init__(self, calendar: Calendar) -> None:
        self._calendar = calendar

    @property
    def key(self) -> str:
        return str(self._calendar.url)

    @property
    def label(self) -> str:
        return str(self._calendar.name or "")

    def event_data(self, start: datetime, end: datetime) -> Sequence[str]:
        searchable = cast("_Searchable", self._calendar)
        found = searchable.search(start=start, end=end, event=True, expand=True)
        return [str(item.data) for item in found]


class _CaldavSession:
    def __init__(self, username: str, password: str) -> None:
        self._client = cast(
            "_Client",
            DAVClient(
                url=ICLOUD_URL, username=username, password=password, timeout=TIMEOUT_SECONDS
            ),
        )

    def calendars(self) -> Sequence[CalendarHandle]:
        return [_CaldavCalendar(calendar) for calendar in self._client.principal().get_calendars()]

    def close(self) -> None:
        self._client.close()


def open_session(username: str, password: str) -> Session:
    """Connect to iCloud; the login itself happens on the first request."""
    return _CaldavSession(username, password)


class AppleCalendarAdapter:
    """iCloud calendars; every VEVENT in the window becomes an `event`. Never partial."""

    def __init__(
        self, tz: tzinfo, clock: Clock, session_factory: SessionFactory = open_session
    ) -> None:
        self._tz = tz
        self._clock = clock
        self._open = session_factory

    @property
    def name(self) -> str:
        return SOURCE_NAME

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        username, password = creds.get("username", ""), creds.get("app_password", "")
        if not username or not password:
            return ValidationResult(
                ok=False, message="Enter your Apple ID and an app-specific password"
            )
        count = await asyncio.to_thread(self._count_calendars, username, password)
        return ValidationResult(ok=True, message=f"Connected to iCloud ({count} calendars)")

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        username, password = creds.get("username", ""), creds.get("app_password", "")
        if not username or not password:
            msg = "Failed to fetch iCloud calendars: the Apple ID or app password is missing"
            raise AuthExpired(msg)
        fetched_at = self._clock.now()
        return await asyncio.to_thread(self._fetch, username, password, window, fetched_at)

    def _count_calendars(self, username: str, password: str) -> int:
        failure: Exception | None = None
        count = 0
        session = self._open(username, password)
        try:
            count = len(session.calendars())
        except Exception as exc:  # noqa: BLE001  (any vendor error must become ours, unchained)
            failure = _translate(exc)
        finally:
            session.close()
        if failure is not None:
            raise failure
        return count

    def _fetch(
        self, username: str, password: str, window: TimeWindow, fetched_at: datetime
    ) -> list[Event]:
        failure: Exception | None = None
        events: list[Event] = []
        session = self._open(username, password)
        try:
            for calendar in session.calendars():
                for data in calendar.event_data(
                    window.start - EXPANSION_PAD, window.end + EXPANSION_PAD
                ):
                    events.extend(self._parse(data, calendar, window, fetched_at))
        except (DAVError, OSError) as exc:
            failure = _translate(exc)
        except ValueError:
            failure = FatalError("Failed to read iCloud calendars: an item could not be parsed")
        except Exception as exc:  # noqa: BLE001  (any vendor error must become ours, unchained)
            failure = _translate(exc)
        finally:
            session.close()
        if failure is not None:
            raise failure
        return events

    def _parse(
        self, data: str, calendar: CalendarHandle, window: TimeWindow, fetched_at: datetime
    ) -> list[Event]:
        return events_in_window(
            parse_calendar(data),
            source=SOURCE_NAME,
            scope=calendar.key,
            tz=self._tz,
            window=window,
            fetched_at=fetched_at,
            extra_raw={"calendar": calendar.label},
        )


def _translate(exc: Exception) -> Exception:
    """Map a CalDAV/network failure to ours; nothing from exc is kept (it may quote the login)."""
    if isinstance(exc, AuthorizationError):
        return AuthExpired("iCloud rejected the Apple ID or app-specific password")
    return TransientError(
        f"iCloud could not be reached or answered with an error ({type(exc).__name__})"
    )
