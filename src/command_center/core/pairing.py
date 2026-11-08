"""Phone pairing: token hashing, credential models, device names and the failure limiter."""

import hashlib
import hmac
import re
import unicodedata
from datetime import datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

PAIRING_TOKEN_BYTES = 16
CREDENTIAL_TOKEN_BYTES = 32
DEVICE_ID_BYTES = 16
PAIRING_TTL = timedelta(minutes=5)
ACCESS_TTL = timedelta(minutes=15)
MAX_DEVICE_NAME = 64
FAILURE_LIMIT = 5
LOCK_DURATION = timedelta(seconds=60)
DEFAULT_DEVICE_NAME = "Phone"

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}", re.ASCII)
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


class Device(BaseModel):
    """A paired phone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    name: str
    created_at: AwareDatetime
    last_seen_at: AwareDatetime


class RefreshRecord(BaseModel):
    """What a store knows about a refresh credential hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    superseded: bool


class PairingOffer(BaseModel):
    """A one-time pairing token to show as a QR code; the token is hidden from repr."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str = Field(repr=False)
    expires_at: AwareDatetime


class IssuedTokens(BaseModel):
    """The credentials handed to a phone once; both tokens are hidden from repr."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    access_token: str = Field(repr=False)
    access_expires_at: AwareDatetime
    refresh_token: str = Field(repr=False)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of the UTF-8 token; only digests are ever stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hashes_match(a: str, b: str) -> bool:
    """Compare two digests in constant time."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def is_plausible_token(token: str) -> bool:
    """Cheaply reject anything that cannot be one of our tokens, before hashing it."""
    return _TOKEN_PATTERN.fullmatch(token) is not None


def clean_device_name(raw: str | None) -> str:
    """Return a safe display name: no control or format characters, one-space gaps, at most 64."""
    if raw is None:
        return DEFAULT_DEVICE_NAME
    words = (
        "".join(c for c in word if unicodedata.category(c) not in _DROPPED_CATEGORIES)
        for word in raw.split()
    )
    name = " ".join(word for word in words if word)[:MAX_DEVICE_NAME].rstrip()
    return name or DEFAULT_DEVICE_NAME


class FailureLimiter:
    """Locks out guessing: the `limit`-th consecutive failure starts a lock of `lock`."""

    def __init__(self, limit: int = FAILURE_LIMIT, lock: timedelta = LOCK_DURATION) -> None:
        self._limit = limit
        self._lock = lock
        self._failures = 0
        self._locked_until: datetime | None = None

    def locked_for(self, now: datetime) -> timedelta | None:
        """Return the time left of an active lock, else None."""
        if self._locked_until is None or now >= self._locked_until:
            return None
        return self._locked_until - now

    def record_failure(self, now: datetime) -> None:
        """Count a failure; a failure during a lock is ignored, so a lock is never extended."""
        if self.locked_for(now) is not None:
            return
        if self._locked_until is not None:
            self._locked_until = None
            self._failures = 0
        self._failures += 1
        if self._failures >= self._limit:
            self._locked_until = now + self._lock

    def record_success(self) -> None:
        """Reset the count; an active lock stays."""
        self._failures = 0
