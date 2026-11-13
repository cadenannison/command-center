"""Shared building blocks: the Event every source normalises into, plus small result types."""

import hashlib
from collections.abc import Mapping
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field

from command_center.core.priority import priority as derive_priority

EventKind = Literal["event", "assignment", "email", "weather", "task"]


class Event(BaseModel):
    """One normalised item (calendar event, assignment, email, weather). Immutable."""

    model_config = ConfigDict(frozen=True)

    id: str
    user_id: str = "local"
    source: str
    kind: EventKind
    title: str
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    due: AwareDatetime | None = None
    urgency: int = Field(default=0, ge=0, le=100)
    link: str | None = None
    status: str | None = None
    raw: dict[str, object] = Field(default_factory=dict[str, object])
    fetched_at: AwareDatetime
    # True when the user attached a note; set by the agenda service, never stored on the event row.
    has_note: bool = False
    # Set by the agenda service from the ledger (decision 0398); a snooze shows only while it holds.
    dismissed_at: AwareDatetime | None = None
    snoozed_until: AwareDatetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def priority(self) -> int | None:
        """1-10 priority derived from `urgency`; None when done or urgency is 0. Not stored."""
        return derive_priority(self.urgency, done=self.status == "done")


class ValidationResult(BaseModel):
    """Outcome of checking credentials; updated_creds carries refreshed tokens to persist."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    message: str
    updated_creds: Mapping[str, str] | None = Field(default=None, repr=False)


_LAST4_MIN_LENGTH = 8


class SecretStatus(BaseModel):
    """What the settings API may reveal about a secret: whether it is set and its last 4 chars.

    `last4` is None for an unset secret and for any value shorter than 8 characters, where four
    characters would give away too much of the value.
    """

    model_config = ConfigDict(frozen=True)

    set: bool
    last4: str | None = None


def secret_status(value: str) -> SecretStatus:
    """Status of a stored value; every SecretStore derives its status from this one rule."""
    last4 = value[-4:] if len(value) >= _LAST4_MIN_LENGTH else None
    return SecretStatus(set=True, last4=last4)


def event_id(source: str, source_id: str) -> str:
    """Stable 32-hex id for an item, derived from its source and the source's own id."""
    # NUL separator so ("a:b", "c") and ("a", "b:c") cannot collide.
    return hashlib.sha256(f"{source}\x00{source_id}".encode()).hexdigest()[:32]
