"""Which credential keys are secret, per source: the one place that decides (decision 0100)."""

from collections.abc import Mapping

# The allow-list is of the keys that may be shown back; everything else, and every key of a source
# or key not listed here, is a secret. A new key is therefore hidden until someone lists it.
NON_SECRET_KEYS: Mapping[str, frozenset[str]] = {
    "canvas": frozenset({"base_url"}),
    "apple_calendar": frozenset({"username"}),
    "weather": frozenset({"latitude", "longitude"}),
}


def is_secret(source: str, key: str) -> bool:
    """Whether the value of key under source must never leave the secret store."""
    return key not in NON_SECRET_KEYS.get(source, frozenset())
