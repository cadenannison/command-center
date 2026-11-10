"""SQLAlchemy AppSettingStore: a small key-value table, one row per user and key."""

from pathlib import Path

from sqlalchemy import Engine, String, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class _Base(DeclarativeBase):
    pass


class _AppSettingRow(_Base):
    __tablename__ = "app_settings"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))


class SqliteAppSettingStore:
    """AppSettingStore over SQLAlchemy; the same code runs on SQLite and Postgres."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def get(self, key: str, *, user_id: str = "local") -> str | None:
        statement = select(_AppSettingRow.value).where(
            _AppSettingRow.user_id == user_id, _AppSettingRow.key == key
        )
        with self._sessions() as session:
            return session.scalars(statement).first()

    def set(self, key: str, value: str, *, user_id: str = "local") -> None:
        with self._sessions.begin() as session:
            session.merge(_AppSettingRow(user_id=user_id, key=key, value=value))


def create_app_setting_store(database_url: str) -> SqliteAppSettingStore:
    """Open the database at database_url, creating the file's directory and the table."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, hide_parameters=True)
    _Base.metadata.create_all(engine)
    return SqliteAppSettingStore(engine)
