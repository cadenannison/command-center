"""A fake Gmail service object (the googleapiclient boundary) plus message and thread builders.

Shapes follow the Gmail v1 discovery document: Thread.id, Message.id/labelIds/snippet/internalDate
(epoch milliseconds as a string) and payload.headers[{name, value}].
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httplib2
from googleapiclient.errors import HttpError  # pyright: ignore[reportMissingTypeStubs]

from command_center.adapters.gmail import GmailAdapter
from command_center.core.windows import TimeWindow
from fakes import FakeClock

ME = "me@example.com"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=datetime(2026, 10, 24, tzinfo=UTC), end=datetime(2027, 1, 6, tzinfo=UTC))
CLIENT_JSON = json.dumps(
    {
        "installed": {
            "client_id": "fake-client-id.apps.example.com",
            "client_secret": "fake-client-secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
)
CREDS = {"client_json": CLIENT_JSON, "refresh_token": "fake-refresh-token"}

type Json = dict[str, object]


def http_error(status: int, reason: str = "") -> HttpError:
    body = {"error": {"errors": [{"reason": reason}]}} if reason else {}
    return HttpError(httplib2.Response({"status": status}), json.dumps(body).encode())


def message(  # noqa: PLR0913  (a builder: every argument is an optional header or label)
    *,
    sent: datetime,
    sender: str = "Alex Doe <alex@school.edu>",
    to: str = ME,
    cc: str | None = None,
    subject: str = "Question about the project",
    labels: tuple[str, ...] = ("INBOX",),
    snippet: str = "Can you send the draft?",
    extra: Mapping[str, str] | None = None,
) -> Json:
    headers = {"From": sender, "To": to, "Subject": subject}
    if cc is not None:
        headers["Cc"] = cc
    headers.update(extra or {})
    return {
        "id": f"m-{int(sent.timestamp())}",
        "labelIds": list(labels),
        "snippet": snippet,
        "internalDate": str(int(sent.timestamp() * 1000)),
        "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]},
    }


def thread(thread_id: str, *messages: Json) -> Json:
    return {"id": thread_id, "messages": list(messages)}


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


class _Request:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def execute(self) -> object:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakeGmail:
    """Stands in for the object googleapiclient.discovery.build returns."""

    def __init__(
        self,
        threads: Mapping[str, Json] | None = None,
        *,
        pages: int = 1,
        profile: object | Exception = None,
        get_errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self.threads_by_id = dict(threads or {})
        self._pages = pages
        self._profile = {"emailAddress": ME} if profile is None else profile
        self._get_errors = dict(get_errors or {})
        self.list_calls: list[Json] = []
        self.get_calls: list[Json] = []
        self.profile_calls = 0

    def users(self) -> "FakeGmail":
        return self

    def threads(self) -> "FakeGmail":
        return self

    def getProfile(self, **params: object) -> _Request:  # noqa: N802
        assert params == {"userId": "me"}
        self.profile_calls += 1
        return _Request(self._profile)

    def list(self, **params: object) -> _Request:
        self.list_calls.append(dict(params))
        page = int(str(params["pageToken"] or 0))
        ids = list(self.threads_by_id)
        size = -(-len(ids) // self._pages) if ids else 1
        body: Json = {"threads": [{"id": i, "snippet": ""} for i in ids[page * size :][:size]]}
        if page + 1 < self._pages:
            body["nextPageToken"] = str(page + 1)
        return _Request(body)

    def get(self, **params: object) -> _Request:
        self.get_calls.append(dict(params))
        thread_id = str(params["id"])
        return _Request(self._get_errors.get(thread_id, self.threads_by_id[thread_id]))


def make_adapter(
    fake: FakeGmail,
    *,
    vip_senders: tuple[str, ...] = (),
    muted_senders: tuple[str, ...] = (),
    now: datetime = NOW,
) -> GmailAdapter:
    return GmailAdapter(
        FakeClock(now),
        vip_senders=vip_senders,
        muted_senders=muted_senders,
        service_factory=lambda _creds: fake,
    )
