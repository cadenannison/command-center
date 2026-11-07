"""Ports the pure core depends on. Time, randomness and ids are passed in, never global."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current timezone-aware time."""
        ...


class Rng(Protocol):
    """Source of randomness."""

    def random(self) -> float:
        """Return a float in [0.0, 1.0)."""
        ...


class IdSource(Protocol):
    """Source of unique identifiers."""

    def new_id(self) -> str:
        """Return a new unique id."""
        ...
