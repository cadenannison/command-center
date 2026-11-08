"""Gmail response shapes and the owed-reply heuristic. Pure: no SDK, no I/O (decision 0044).

Split from gmail.py so the vendor SDK stays in one file. No body is read: the adapter asks for
metadata headers, and `raw` carries the sender's display name and the snippet.
"""

import email.header
import email.utils
import html
import re
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from command_center.core.errors import FatalError
from command_center.core.redact import redact, trim
from command_center.core.schema import Event, event_id

SOURCE = "gmail"
QUERY = "newer_than:14d -category:promotions -category:social -category:updates -category:forums"
HEADERS = (
    "From",
    "To",
    "Cc",
    "Subject",
    "List-Unsubscribe",
    "List-Id",
    "Precedence",
    "Auto-Submitted",
)
OVERDUE_AFTER = timedelta(days=2)
TITLE_LIMIT = 120
SNIPPET_LIMIT = 200
THREAD_LINK = "https://mail.google.com/mail/u/0/#all/{thread_id}"
_BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})
_NO_REPLY = re.compile(r"no[-_.]?reply|do[-_.]?not[-_.]?reply")
_WANTS_ATTENTION = frozenset({"STARRED", "IMPORTANT"})


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Profile(_Model):
    """users.getProfile: the signed-in address."""

    emailAddress: str  # noqa: N815  (the API's field name)


class ThreadRef(_Model):
    """One row of threads.list."""

    id: str


class ThreadList(_Model):
    """threads.list: one page of thread ids and the token for the next."""

    threads: list[ThreadRef] = Field(default_factory=list[ThreadRef])
    nextPageToken: str | None = None  # noqa: N815


class _Header(_Model):
    name: str
    value: str


class _Payload(_Model):
    headers: list[_Header] = Field(default_factory=list[_Header])


class Message(_Model):
    """One message of threads.get?format=metadata."""

    id: str
    labelIds: list[str] = Field(default_factory=list[str])  # noqa: N815
    snippet: str = ""
    internalDate: int  # noqa: N815  (epoch milliseconds; the API sends it as a string)
    payload: _Payload = Field(default_factory=_Payload)

    def header(self, name: str) -> str | None:
        """The first header called name, case-insensitively."""
        wanted = name.lower()
        return next((h.value for h in self.payload.headers if h.name.lower() == wanted), None)

    def sent_at(self) -> datetime:
        """When Gmail received or sent the message (internalDate), in UTC."""
        return datetime.fromtimestamp(self.internalDate / 1000, tz=UTC)


class Thread(_Model):
    """threads.get?format=metadata."""

    id: str
    messages: list[Message] = Field(default_factory=list[Message])


def parse[T: BaseModel](model: type[T], data: object) -> T:
    """Validate a response; anything unexpected is a FatalError with fixed text."""
    try:
        return model.model_validate(data)
    except (ValidationError, ValueError):
        msg = "Gmail returned an unexpected response"
        raise FatalError(msg) from None


class SenderRules:
    """The user's VIP and muted senders: exact addresses, or `@domain` for a whole domain."""

    def __init__(self, vips: Collection[str], muted: Collection[str]) -> None:
        self._vips = frozenset(entry.strip().lower() for entry in vips)
        self._muted = frozenset(entry.strip().lower() for entry in muted)

    def is_vip(self, address: str) -> bool:
        """True when the sender is a VIP: such a thread is owed even if only copied."""
        return _listed(self._vips, address)

    def is_muted(self, address: str) -> bool:
        """True when the sender is muted: its threads are never owed."""
        return _listed(self._muted, address)


def _listed(entries: frozenset[str], address: str) -> bool:
    return address in entries or "@" + address.partition("@")[2] in entries


def owed_event(thread: Thread, me: str, now: datetime, rules: SenderRules) -> Event | None:
    """The Event for a thread that still waits on the user's reply, else None."""
    # A draft is not a reply: the last sent or received message decides who owes whom.
    messages = [m for m in thread.messages if "DRAFT" not in m.labelIds]
    if not messages:
        return None
    last = max(messages, key=Message.sent_at)
    sender = _first_address(last.header("From"))
    if "SENT" in last.labelIds or sender == me or _is_bulk(last, sender):
        return None
    if sender is not None and rules.is_muted(sender):
        return None
    if not _addressed_to_user(thread, last, me, sender, rules):
        return None
    started = last.sent_at()
    return Event(
        id=event_id(SOURCE, thread.id),
        source=SOURCE,
        kind="email",
        title=_title(last.header("Subject")),
        start=started,
        link=THREAD_LINK.format(thread_id=thread.id),
        status="overdue" if now - started > OVERDUE_AFTER else "owed",
        raw={"sender": _display_name(last.header("From")), "snippet": _snippet(last)},
        fetched_at=now,
    )


def _addressed_to_user(
    thread: Thread, last: Message, me: str, sender: str | None, rules: SenderRules
) -> bool:
    if me in _addresses(last.header("To")):
        return True
    if sender is not None and rules.is_vip(sender):
        return True
    return any(label in _WANTS_ATTENTION for m in thread.messages for label in m.labelIds)


def _decode(value: str) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(value)))
    except (ValueError, LookupError):
        return value


def _addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr.lower() for _, addr in email.utils.getaddresses([value]) if addr]


def _first_address(value: str | None) -> str | None:
    found = _addresses(value)
    return found[0] if found else None


def _display_name(value: str | None) -> str:
    """The sender's display name; empty when absent or when it is itself an address."""
    if not value:
        return ""
    name = _decode(email.utils.getaddresses([value])[0][0]).strip()
    return "" if "@" in name else name


def _title(subject: str | None) -> str:
    text = " ".join(_decode(subject or "").split())
    return trim(text, TITLE_LIMIT) or "(no subject)"


def _snippet(message: Message) -> str:
    # The snippet is the start of the body: addresses and long numbers are stripped (core.redact).
    return trim(redact(" ".join(html.unescape(message.snippet).split())), SNIPPET_LIMIT)


def _is_bulk(message: Message, sender: str | None) -> bool:
    if message.header("List-Unsubscribe") is not None or message.header("List-Id") is not None:
        return True
    precedence = (message.header("Precedence") or "").strip().lower()
    auto = (message.header("Auto-Submitted") or "no").strip().lower()
    local = (sender or "").partition("@")[0]
    return precedence in _BULK_PRECEDENCE or auto != "no" or _NO_REPLY.search(local) is not None
