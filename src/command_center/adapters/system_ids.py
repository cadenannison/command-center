"""The real IdSource: random UUIDs."""

import uuid


class UuidIdSource:
    """IdSource that returns a fresh UUID4 as 32 hex characters."""

    def new_id(self) -> str:
        return uuid.uuid4().hex
