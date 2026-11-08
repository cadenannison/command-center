"""SQLAlchemy DeviceStore: pairing tokens, paired phones and their credential hashes.

Only SHA-256 digests are stored, never a token. Times are fixed-width UTC strings, so SQL can
compare them as text. Every state change is one transaction, so a token that is taken or rotated
cannot be taken or rotated a second time.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Boolean, Engine, Index, String, create_engine, delete, insert, select, update
from sqlalchemy.engine import CursorResult, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from command_center.core.pairing import Device, RefreshRecord, hashes_match

_ACCESS = "access"
_REFRESH = "refresh"


class _Base(DeclarativeBase):
    pass


class _PairingRow(_Base):
    __tablename__ = "pairing_tokens"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    expires_at: Mapped[str] = mapped_column(String)


class _DeviceRow(_Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[str] = mapped_column(String)


class _CredentialRow(_Base):
    __tablename__ = "device_credentials"
    __table_args__ = (Index("ix_device_credentials_device", "device_id"),)

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    # Access credentials expire; refresh credentials end only by rotation or revocation.
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)


def _stamp(moment: datetime) -> str:
    if moment.utcoffset() is None:
        msg = "Refusing to store a naive datetime"
        raise ValueError(msg)
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


class SqliteDeviceStore:
    """DeviceStore over SQLAlchemy.

    Rows are found by the digest of what the caller sent, so how long a lookup takes says nothing
    about a secret. The read paths still compare the stored digest in constant time; the
    state-changing statements match on the digest inside the SQL, which is also what makes them
    atomic (decision 0057).
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def put_pairing(
        self,
        token_hash: str,
        expires_at: datetime,
        now: datetime,  # noqa: ARG002  (the port offers it for stores that prune by age)
    ) -> None:
        with self._sessions.begin() as session:
            session.execute(delete(_PairingRow))  # expired and superseded offers alike
            session.execute(
                insert(_PairingRow).values(token_hash=token_hash, expires_at=_stamp(expires_at))
            )

    def take_pairing(self, token_hash: str, now: datetime) -> bool:
        statement = (
            delete(_PairingRow)
            .where(_PairingRow.token_hash == token_hash)
            .returning(_PairingRow.expires_at)
        )
        # The DELETE is the comparison and the claim in one statement: it removes the row for
        # exactly this digest, so a second caller finds nothing even if both run at once.
        with self._sessions.begin() as session:
            row = session.execute(statement).first()
        return row is not None and _moment(row.expires_at) > now

    def add_device(
        self, device: Device, refresh_hash: str, access_hash: str, access_expires_at: datetime
    ) -> None:
        with self._sessions.begin() as session:
            session.add(
                _DeviceRow(
                    id=device.id,
                    name=device.name,
                    created_at=_stamp(device.created_at),
                    last_seen_at=_stamp(device.last_seen_at),
                )
            )
            session.add(
                _CredentialRow(
                    token_hash=refresh_hash, device_id=device.id, kind=_REFRESH, superseded=False
                )
            )
            session.add(
                _CredentialRow(
                    token_hash=access_hash,
                    device_id=device.id,
                    kind=_ACCESS,
                    expires_at=_stamp(access_expires_at),
                    superseded=False,
                )
            )

    def rotate_refresh(
        self,
        old_refresh_hash: str,
        new_refresh_hash: str,
        new_access_hash: str,
        access_expires_at: datetime,
        now: datetime,
    ) -> str | None:
        claim = (
            update(_CredentialRow)
            .where(
                _CredentialRow.token_hash == old_refresh_hash,
                _CredentialRow.kind == _REFRESH,
                _CredentialRow.superseded.is_(False),
                _CredentialRow.device_id.in_(select(_DeviceRow.id)),
            )
            .values(superseded=True)
            .returning(_CredentialRow.device_id)
        )
        with self._sessions.begin() as session:
            claimed = session.execute(claim).first()
            if claimed is None:
                return None
            device_id: str = claimed.device_id
            session.execute(
                delete(_CredentialRow).where(
                    _CredentialRow.device_id == device_id, _CredentialRow.kind == _ACCESS
                )
            )
            session.add(
                _CredentialRow(
                    token_hash=new_refresh_hash,
                    device_id=device_id,
                    kind=_REFRESH,
                    superseded=False,
                )
            )
            session.add(
                _CredentialRow(
                    token_hash=new_access_hash,
                    device_id=device_id,
                    kind=_ACCESS,
                    expires_at=_stamp(access_expires_at),
                    superseded=False,
                )
            )
            session.execute(
                update(_DeviceRow)
                .where(_DeviceRow.id == device_id)
                .values(last_seen_at=_stamp(now))
            )
        return device_id

    def refresh_record(self, refresh_hash: str) -> RefreshRecord | None:
        statement = select(
            _CredentialRow.token_hash, _CredentialRow.device_id, _CredentialRow.superseded
        ).where(_CredentialRow.token_hash == refresh_hash, _CredentialRow.kind == _REFRESH)
        with self._sessions() as session:
            row = session.execute(statement).first()
        if row is None or not hashes_match(row.token_hash, refresh_hash):
            return None
        return RefreshRecord(device_id=row.device_id, superseded=row.superseded)

    def device_for_access(self, access_hash: str, now: datetime) -> str | None:
        # Joining devices makes a credential whose device was revoked mid-rotation inert, even where
        # the database lets a delete miss rows another transaction has not committed yet.
        statement = (
            select(_CredentialRow.token_hash, _CredentialRow.device_id, _CredentialRow.expires_at)
            .join(_DeviceRow, _DeviceRow.id == _CredentialRow.device_id)
            .where(_CredentialRow.token_hash == access_hash, _CredentialRow.kind == _ACCESS)
        )
        with self._sessions() as session:
            row = session.execute(statement).first()
        if row is None or not hashes_match(row.token_hash, access_hash) or row.expires_at is None:
            return None
        return row.device_id if _moment(row.expires_at) > now else None

    def list_devices(self) -> list[Device]:
        statement = select(_DeviceRow).order_by(_DeviceRow.created_at, _DeviceRow.id)
        with self._sessions() as session:
            return [
                Device(
                    id=row.id,
                    name=row.name,
                    created_at=_moment(row.created_at),
                    last_seen_at=_moment(row.last_seen_at),
                )
                for row in session.scalars(statement)
            ]

    def remove_device(self, device_id: str) -> bool:
        with self._sessions.begin() as session:
            session.execute(delete(_CredentialRow).where(_CredentialRow.device_id == device_id))
            result = cast(
                "CursorResult[Any]",
                session.execute(delete(_DeviceRow).where(_DeviceRow.id == device_id)),
            )
            return result.rowcount > 0


def create_device_store(database_url: str) -> SqliteDeviceStore:
    """Open the database at database_url, creating the file's directory and the tables."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    # Hidden parameters keep digests out of error messages and logs (decision 0027).
    engine = create_engine(url, hide_parameters=True)
    _Base.metadata.create_all(engine)
    return SqliteDeviceStore(engine)
