"""Retry backoff and a circuit breaker, both pure: time and randomness are passed in."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from command_center.core.ports import Clock, Rng


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with interval jitter; attempts are 1-based."""

    max_attempts: int
    base_delay: timedelta
    factor: float
    cap: timedelta

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            msg = f"RetryPolicy max_attempts must be at least 1, got {self.max_attempts}"
            raise ValueError(msg)
        if self.base_delay <= timedelta(0):
            msg = f"RetryPolicy base_delay must be positive, got {self.base_delay}"
            raise ValueError(msg)
        if not self.factor >= 1:
            msg = f"RetryPolicy factor must be at least 1, got {self.factor}"
            raise ValueError(msg)
        if self.cap < self.base_delay:
            msg = f"RetryPolicy cap {self.cap} must not be below base_delay {self.base_delay}"
            raise ValueError(msg)

    def _step(self, attempt: int) -> timedelta:
        """E(n) = min(cap, base_delay * factor**(n-1)), with E(0) = E(1)."""
        exponent = max(attempt, 1) - 1
        try:
            scaled = self.base_delay.total_seconds() * self.factor**exponent
        except OverflowError:
            return self.cap
        if scaled >= self.cap.total_seconds():
            return self.cap
        return min(self.cap, timedelta(seconds=scaled))

    def delay(self, attempt: int, rng: Rng) -> timedelta:
        """Wait before attempt + 1 after `attempt` failed; never above cap, never decreasing.

        delay(1) is exactly E(1). For n >= 2 it is drawn uniformly from [E(n-1), E(n)], and
        those intervals touch end to end, so any rng draws keep the sequence non-decreasing.
        """
        if attempt < 1:
            msg = f"RetryPolicy.delay needs attempt >= 1, got {attempt}"
            raise ValueError(msg)
        high = self._step(attempt)
        if attempt == 1:
            return high
        draw = rng.random()
        if not 0.0 <= draw < 1.0:
            msg = f"Rng.random() must return a float in [0, 1), got {draw}"
            raise ValueError(msg)
        low = self._step(attempt - 1)
        return low + max(high - low, timedelta(0)) * draw

    def exhausted(self, attempt: int) -> bool:
        """True when `attempt` was the last one allowed."""
        return attempt >= self.max_attempts


DEFAULT_RETRY_POLICY = RetryPolicy(
    max_attempts=5, base_delay=timedelta(seconds=5), factor=2.0, cap=timedelta(minutes=5)
)
DEFAULT_VISIBILITY_TIMEOUT = timedelta(minutes=5)


class BreakerPhase(StrEnum):
    """Where a circuit breaker is in its cycle."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class BreakerState:
    """Plain-data breaker state; the caller stores it and passes it back in."""

    phase: BreakerPhase = BreakerPhase.CLOSED
    failures: int = 0
    opened_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.failures < 0:
            msg = f"BreakerState failures must not be negative, got {self.failures}"
            raise ValueError(msg)
        if self.opened_at is not None and self.opened_at.utcoffset() is None:
            msg = "BreakerState opened_at must be timezone-aware"
            raise ValueError(msg)
        if self.phase is not BreakerPhase.CLOSED and self.opened_at is None:
            msg = f"BreakerState in phase {self.phase.value} needs opened_at"
            raise ValueError(msg)


class CircuitBreaker:
    """Stops calling a failing dependency until a cool-down passes, then allows one trial call.

    Holds only immutable config; every method takes and returns a BreakerState. In HALF_OPEN
    `allow` is True, and the caller must serialise the single trial call (for example with a
    lock or a Redis SET NX) and report it through record_success / record_failure.
    """

    def __init__(self, failure_threshold: int, cool_down: timedelta, clock: Clock) -> None:
        if failure_threshold < 1:
            msg = f"CircuitBreaker failure_threshold must be at least 1, got {failure_threshold}"
            raise ValueError(msg)
        if cool_down <= timedelta(0):
            msg = f"CircuitBreaker cool_down must be positive, got {cool_down}"
            raise ValueError(msg)
        self._failure_threshold = failure_threshold
        self._cool_down = cool_down
        self._clock = clock

    def initial(self) -> BreakerState:
        """Return the starting state: closed with no failures."""
        return BreakerState()

    def current(self, state: BreakerState) -> BreakerState:
        """Return state as of now: OPEN becomes HALF_OPEN once the cool-down has elapsed."""
        if state.phase is not BreakerPhase.OPEN or state.opened_at is None:
            return state
        elapsed = self._clock.now().astimezone(UTC) - state.opened_at.astimezone(UTC)
        if elapsed >= self._cool_down:
            return BreakerState(BreakerPhase.HALF_OPEN, state.failures, state.opened_at)
        return state

    def allow(self, state: BreakerState) -> bool:
        """True when a call may be made now (closed, or the half-open trial)."""
        return self.current(state).phase is not BreakerPhase.OPEN

    def record_success(self, state: BreakerState) -> BreakerState:
        """Close the breaker and forget failures."""
        del state
        return BreakerState()

    def record_failure(self, state: BreakerState) -> BreakerState:
        """Count a failure: may open a closed breaker, reopens a half-open one, else no change."""
        seen = self.current(state)
        if seen.phase is BreakerPhase.OPEN:
            return seen
        failures = seen.failures + 1
        if seen.phase is BreakerPhase.HALF_OPEN or failures >= self._failure_threshold:
            return BreakerState(BreakerPhase.OPEN, failures, self._clock.now())
        return BreakerState(BreakerPhase.CLOSED, failures, None)
