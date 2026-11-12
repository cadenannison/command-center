"""SQLAlchemy stores for dashboards and display settings (decisions 0355 to 0357).

Writes are compare-and-set: one `UPDATE ... WHERE revision = :expected` whose row count says
whether this writer won, so two tabs cannot overwrite each other on SQLite or Postgres.
Timestamps are fixed-width UTC ISO strings, the layout and the settings are JSON text.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import (
    Engine,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from command_center.core.dashboards import (
    MAX_DASHBOARDS,
    Dashboard,
    DashboardLimitError,
    DashboardNotFoundError,
    DashboardSetError,
    DisplayInput,
    DisplaySettings,
    Layout,
    RevisionConflictError,
    layout_json,
    parse_layout,
)

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class _Base(DeclarativeBase):
    pass


class _DashboardRow(_Base):
    __tablename__ = "dashboards"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    layout: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String(32))


class _DisplayRow(_Base):
    __tablename__ = "display_settings"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    settings: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String(32))


def ensure_dashboard_schema(engine: Engine) -> None:
    """Create the two tables if they are missing."""
    _Base.metadata.create_all(engine)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TIME_FORMAT)


def _parse_stamp(value: str) -> datetime:
    return datetime.strptime(value, _TIME_FORMAT).replace(tzinfo=UTC)


def _dashboard(row: _DashboardRow) -> Dashboard:
    return Dashboard(
        id=row.id,
        name=row.name,
        position=row.position,
        layout=parse_layout(row.layout),
        revision=row.revision,
        updated_at=_parse_stamp(row.updated_at),
    )


class SqliteDashboardStore:
    """DashboardStore over SQLAlchemy; the same code runs on SQLite and Postgres."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def list_all(self, *, user_id: str = "local") -> list[Dashboard]:
        with self._sessions() as session:
            return [_dashboard(row) for row in _rows(session, user_id)]

    def get(self, dashboard_id: str, *, user_id: str = "local") -> Dashboard | None:
        with self._sessions() as session:
            row = session.get(_DashboardRow, (user_id, dashboard_id))
            return None if row is None else _dashboard(row)

    def add(
        self, dashboard_id: str, name: str, layout: Layout, now: datetime, *, user_id: str = "local"
    ) -> Dashboard:
        with self._sessions.begin() as session:
            count = session.scalar(
                select(func.count())
                .select_from(_DashboardRow)
                .where(_DashboardRow.user_id == user_id)
            )
            if (count or 0) >= MAX_DASHBOARDS:
                raise DashboardLimitError
            last = session.scalar(
                select(func.max(_DashboardRow.position)).where(_DashboardRow.user_id == user_id)
            )
            row = _DashboardRow(
                user_id=user_id,
                id=dashboard_id,
                name=name,
                position=0 if last is None else last + 1,
                layout=layout_json(layout),
                revision=1,
                updated_at=_stamp(now),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                raise RevisionConflictError from None
            return _dashboard(row)

    def replace(  # noqa: PLR0913
        self,
        dashboard_id: str,
        expected_revision: int,
        name: str,
        layout: Layout,
        now: datetime,
        *,
        user_id: str = "local",
    ) -> Dashboard:
        with self._sessions.begin() as session:
            result = session.execute(
                update(_DashboardRow)
                .where(
                    _DashboardRow.user_id == user_id,
                    _DashboardRow.id == dashboard_id,
                    _DashboardRow.revision == expected_revision,
                )
                .values(
                    name=name,
                    layout=layout_json(layout),
                    revision=_DashboardRow.revision + 1,
                    updated_at=_stamp(now),
                )
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
                _explain_miss(session, user_id, dashboard_id)
            row = session.get(_DashboardRow, (user_id, dashboard_id))
            assert row is not None  # noqa: S101  (the update matched it in this transaction)
            session.refresh(row)
            return _dashboard(row)

    def delete(self, dashboard_id: str, expected_revision: int, *, user_id: str = "local") -> None:
        with self._sessions.begin() as session:
            result = session.execute(
                delete(_DashboardRow).where(
                    _DashboardRow.user_id == user_id,
                    _DashboardRow.id == dashboard_id,
                    _DashboardRow.revision == expected_revision,
                )
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
                _explain_miss(session, user_id, dashboard_id)

    def reorder(self, ids: Sequence[str], *, user_id: str = "local") -> list[Dashboard]:
        with self._sessions.begin() as session:
            rows = _rows(session, user_id)
            if sorted(ids) != sorted(row.id for row in rows):
                raise DashboardSetError
            by_id = {row.id: row for row in rows}
            for position, dashboard_id in enumerate(ids):
                by_id[dashboard_id].position = position
            session.flush()
            return [_dashboard(by_id[dashboard_id]) for dashboard_id in ids]


def _rows(session: Session, user_id: str) -> list[_DashboardRow]:
    statement = (
        select(_DashboardRow)
        .where(_DashboardRow.user_id == user_id)
        .order_by(_DashboardRow.position, _DashboardRow.id)
    )
    return list(session.scalars(statement))


def _explain_miss(session: Session, user_id: str, dashboard_id: str) -> None:
    """Raise the right failure when a compare-and-set touched no row."""
    if session.get(_DashboardRow, (user_id, dashboard_id)) is None:
        raise DashboardNotFoundError
    raise RevisionConflictError


class SqliteDisplaySettingsStore:
    """DisplaySettingsStore over SQLAlchemy: one row per user, compare-and-set on revision."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def get(self, *, user_id: str = "local") -> DisplaySettings:
        with self._sessions() as session:
            row = session.get(_DisplayRow, user_id)
            if row is None:
                return DisplaySettings()
            try:
                values = DisplayInput.model_validate_json(row.settings)
            except ValidationError:
                # A row that no longer parses reads as the defaults; the revision stays, so the
                # next write (with that revision) repairs it.
                values = DisplayInput()
            return DisplaySettings(
                **values.model_dump(),
                revision=row.revision,
                updated_at=_parse_stamp(row.updated_at),
            )

    def replace(
        self,
        settings: DisplaySettings,
        expected_revision: int,
        now: datetime,
        *,
        user_id: str = "local",
    ) -> DisplaySettings:
        body = DisplayInput(**settings.model_dump(exclude={"revision", "updated_at"}))
        text = body.model_dump_json()
        with self._sessions.begin() as session:
            if expected_revision == 0:
                session.add(
                    _DisplayRow(user_id=user_id, settings=text, revision=1, updated_at=_stamp(now))
                )
                try:
                    session.flush()
                except IntegrityError:
                    raise RevisionConflictError from None
            else:
                result = session.execute(
                    update(_DisplayRow)
                    .where(
                        _DisplayRow.user_id == user_id, _DisplayRow.revision == expected_revision
                    )
                    .values(settings=text, revision=expected_revision + 1, updated_at=_stamp(now))
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
                    raise RevisionConflictError
            return DisplaySettings(
                **body.model_dump(),
                revision=expected_revision + 1,
                updated_at=_parse_stamp(_stamp(now)),
            )


def _engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, hide_parameters=True)
    ensure_dashboard_schema(engine)
    return engine


def create_dashboard_store(database_url: str) -> SqliteDashboardStore:
    """Open the database at database_url, creating the file's directory and the tables."""
    return SqliteDashboardStore(_engine(database_url))


def create_display_settings_store(database_url: str) -> SqliteDisplaySettingsStore:
    """Open the database at database_url, creating the file's directory and the tables."""
    return SqliteDisplaySettingsStore(_engine(database_url))
