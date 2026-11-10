"""Column types shared by the SQLAlchemy tables."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """Stores instants as UTC and returns them timezone-aware (SQLite drops the zone itself)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002
    ) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            msg = "Refusing to store a naive datetime"
            raise ValueError(msg)
        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002
    ) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
