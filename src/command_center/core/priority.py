"""Priority 1-10 derived from the 0-100 urgency score."""

MAX_PRIORITY = 10
_BUCKET = 10


def priority(urgency: int, *, done: bool = False) -> int | None:
    """Return ceil(urgency / 10) clamped to 1..10, or None when done or urgency is 0."""
    if done or urgency <= 0:
        return None
    # Integer ceiling division: floats could round a boundary such as 30 / 10 the wrong way.
    return min(MAX_PRIORITY, -(-urgency // _BUCKET))
