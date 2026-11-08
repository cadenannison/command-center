"""Phone pairing: a one-time token becomes a device credential that rotates on every refresh."""

import logging
import math
import threading
from datetime import datetime

from command_center.core.pairing import (
    ACCESS_TTL,
    CREDENTIAL_TOKEN_BYTES,
    DEVICE_ID_BYTES,
    PAIRING_TOKEN_BYTES,
    PAIRING_TTL,
    Device,
    FailureLimiter,
    IssuedTokens,
    PairingOffer,
    clean_device_name,
    hash_token,
    is_plausible_token,
)
from command_center.core.ports import Clock, DeviceStore, TokenSource
from command_center.services.errors import CredentialRejectedError, PairingLockedError

logger = logging.getLogger(__name__)


class PairingService:
    """Issues pairing tokens and device credentials; only SHA-256 hashes reach the store.

    Failed `pair` calls and failed `refresh` calls each have their own lock (5 failures, then
    60 s). The lock is global, not per client: behind Tailscale Serve every request arrives from
    127.0.0.1, so there is no client address to key on, and a lock that one caller can trip for
    the single user is the safer way to fail (decision 0057).
    """

    def __init__(
        self,
        store: DeviceStore,
        tokens: TokenSource,
        clock: Clock,
        *,
        base_url: str | None = None,
    ) -> None:
        self._store = store
        self._tokens = tokens
        self._clock = clock
        self._base_url = base_url
        self._pair_limiter = FailureLimiter()
        self._refresh_limiter = FailureLimiter()
        self._guard = threading.Lock()  # handlers run on worker threads; the limiters are shared

    @property
    def base_url(self) -> str | None:
        """The tailnet URL the phone should be told to use, or None when none is configured."""
        return self._base_url

    def start_pairing(self) -> PairingOffer:
        """Make a one-time pairing token, valid five minutes. It replaces any unused one."""
        now = self._clock.now()
        token = self._tokens.new_token(PAIRING_TOKEN_BYTES)
        expires_at = now + PAIRING_TTL
        self._store.put_pairing(hash_token(token), expires_at, now)
        logger.info("pairing token issued", extra={"reason": "pairing_started"})
        return PairingOffer(token=token, expires_at=expires_at)

    def pair(self, token: str, device_name: str | None) -> IssuedTokens:
        """Exchange a pairing token for a new device's credentials. The token works once."""
        now = self._clock.now()
        with self._guard:
            self._raise_if_locked(self._pair_limiter, now)
            accepted = is_plausible_token(token) and self._store.take_pairing(
                hash_token(token), now
            )
            if not accepted:
                self._pair_limiter.record_failure(now)
                logger.warning("pairing rejected", extra={"reason": "pairing_token_invalid"})
                raise CredentialRejectedError
            self._pair_limiter.record_success()
        device = Device(
            id=self._tokens.new_token(DEVICE_ID_BYTES),
            name=clean_device_name(device_name),
            created_at=now,
            last_seen_at=now,
        )
        issued = self._new_credentials(device.id, now)
        self._store.add_device(
            device,
            hash_token(issued.refresh_token),
            hash_token(issued.access_token),
            issued.access_expires_at,
        )
        logger.info("device paired", extra={"device_id": device.id, "reason": "paired"})
        return issued

    def refresh(self, refresh_token: str) -> IssuedTokens:
        """Swap a refresh credential for a new pair. Reusing a swapped one revokes the device."""
        now = self._clock.now()
        with self._guard:
            self._raise_if_locked(self._refresh_limiter, now)
            outcome = self._rotate(refresh_token, now)
            if isinstance(outcome, IssuedTokens):
                self._refresh_limiter.record_success()
                return outcome
            self._refresh_limiter.record_failure(now)
        raise CredentialRejectedError

    def authenticate(self, access_token: str) -> str | None:
        """The id of the device this unexpired access token belongs to, or None."""
        if not is_plausible_token(access_token):
            return None
        return self._store.device_for_access(hash_token(access_token), self._clock.now())

    def devices(self) -> list[Device]:
        """Every paired device, oldest first."""
        return self._store.list_devices()

    def revoke(self, device_id: str) -> bool:
        """Delete a device and its credentials at once; False if there is no such device."""
        removed = self._store.remove_device(device_id)
        if removed:
            logger.info("device revoked", extra={"device_id": device_id, "reason": "revoked"})
        return removed

    def _rotate(self, refresh_token: str, now: datetime) -> IssuedTokens | None:
        if not is_plausible_token(refresh_token):
            logger.warning("refresh rejected", extra={"reason": "refresh_credential_invalid"})
            return None
        old_hash = hash_token(refresh_token)
        new_refresh = self._tokens.new_token(CREDENTIAL_TOKEN_BYTES)
        new_access = self._tokens.new_token(CREDENTIAL_TOKEN_BYTES)
        expires_at = now + ACCESS_TTL
        device_id = self._store.rotate_refresh(
            old_hash, hash_token(new_refresh), hash_token(new_access), expires_at, now
        )
        if device_id is not None:
            return IssuedTokens(
                device_id=device_id,
                access_token=new_access,
                access_expires_at=expires_at,
                refresh_token=new_refresh,
            )
        record = self._store.refresh_record(old_hash)
        if record is not None and record.superseded:
            self._store.remove_device(record.device_id)
            logger.warning(
                "refresh credential reuse; device revoked",
                extra={"device_id": record.device_id, "reason": "refresh_reuse"},
            )
        else:
            logger.warning("refresh rejected", extra={"reason": "refresh_credential_unknown"})
        return None

    def _new_credentials(self, device_id: str, now: datetime) -> IssuedTokens:
        return IssuedTokens(
            device_id=device_id,
            access_token=self._tokens.new_token(CREDENTIAL_TOKEN_BYTES),
            access_expires_at=now + ACCESS_TTL,
            refresh_token=self._tokens.new_token(CREDENTIAL_TOKEN_BYTES),
        )

    @staticmethod
    def _raise_if_locked(limiter: FailureLimiter, now: datetime) -> None:
        left = limiter.locked_for(now)
        if left is not None:
            raise PairingLockedError(max(1, math.ceil(left.total_seconds())))
