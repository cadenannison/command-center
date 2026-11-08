"""Gmail source: threads that probably still owe the user a reply. gmail.readonly only.

The only importer of googleapiclient and google_auth_oauthlib (docs/MAP.md). It also imports
google-auth, which shares the `google` namespace with google-genai (decision 0043). The owed-reply
heuristic lives in gmail_mail.py (decision 0044).

The user brings their own OAuth desktop client (decision 0003). Creds: `client_json` (the pasted
client file) and `refresh_token`. Access tokens are never stored: every call rebuilds the
credentials from those two values. Messages are fixed text, never a token, the client file or
a vendor message.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol, cast

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp  # pyright: ignore[reportMissingTypeStubs]
from google_auth_oauthlib.flow import (  # pyright: ignore[reportMissingTypeStubs]
    InstalledAppFlow,
    WSGITimeoutError,
)
from googleapiclient.discovery import build  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from googleapiclient.errors import HttpError  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, ConfigDict, ValidationError

from command_center.adapters.gmail_mail import (
    HEADERS,
    QUERY,
    SOURCE,
    Profile,
    SenderRules,
    Thread,
    ThreadList,
    owed_event,
    parse,
)
from command_center.core.errors import AuthExpired, FatalError, SourceError, TransientError
from command_center.core.ports import Clock
from command_center.core.schema import Event, ValidationResult
from command_center.core.windows import TimeWindow

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SIGN_IN_TIMEOUT_SECONDS = 180
HTTP_TIMEOUT_SECONDS = 15
LOOPBACK = "127.0.0.1"  # the sign-in server must never listen beyond this machine
PAGE_SIZE = 100
MAX_PAGES = 20  # 2000 threads; more than that raises rather than returning a partial list
AUTH_EXPIRED_MESSAGE = "Google rejected the saved sign-in; reconnect Gmail"
_UNAUTHORIZED = 401
_FORBIDDEN = 403
_NOT_FOUND = 404
_TOO_MANY = 429
_SERVER_ERROR = 500
_THROTTLE_REASONS = frozenset({"ratelimitexceeded", "userratelimitexceeded", "quotaexceeded"})


class SignInTimedOut(Exception):  # noqa: N818  (reads as a state, not an error class)
    """The browser sign-in did not finish in time."""


class SignInFailed(Exception):  # noqa: N818  (reads as a state, not an error class)
    """The browser sign-in ended without a refresh token."""


# ---------------------------------------------------------------- the slice of the API we use


class _Executable(Protocol):
    def execute(self) -> object: ...


class _ThreadsApi(Protocol):
    """Keyword-only, named as in the discovery document (userId, q, maxResults, pageToken...)."""

    def list(self, **params: object) -> _Executable: ...

    def get(self, **params: object) -> _Executable: ...


class _UsersApi(Protocol):
    def threads(self) -> _ThreadsApi: ...

    def getProfile(self, **params: object) -> _Executable: ...  # noqa: N802


class GmailService(Protocol):
    """The part of a googleapiclient Gmail resource the adapter calls; tests supply a fake."""

    def users(self) -> _UsersApi: ...


type ServiceFactory = Callable[[Mapping[str, str]], GmailService]
type SignIn = Callable[[Mapping[str, object], int], str]


class _Installed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    client_id: str
    client_secret: str
    token_uri: str = "https://oauth2.googleapis.com/token"  # noqa: S105  (a URL, not a secret)


class _ClientFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    installed: _Installed


# ---------------------------------------------------------------- the adapter


class GmailAdapter:
    """SourceAdapter for Gmail: threads waiting on the user's reply (decision 0044)."""

    def __init__(  # noqa: PLR0913  (keyword-only: two sender lists and three test seams)
        self,
        clock: Clock,
        *,
        vip_senders: Sequence[str] = (),
        muted_senders: Sequence[str] = (),
        service_factory: ServiceFactory | None = None,
        sign_in: SignIn | None = None,
        sign_in_timeout: float = SIGN_IN_TIMEOUT_SECONDS,
    ) -> None:
        self._clock = clock
        self._rules = SenderRules(vip_senders, muted_senders)
        self._service_factory = service_factory or default_service
        self._sign_in = sign_in or run_sign_in
        self._sign_in_timeout = sign_in_timeout

    @property
    def name(self) -> str:
        """The source name stored on every Event: "gmail"."""
        return SOURCE

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Sign in when there is no refresh token, else check the saved one; never raises."""
        try:
            return await self._validate(creds)
        except AuthExpired:
            return ValidationResult(ok=False, message=AUTH_EXPIRED_MESSAGE)
        except SourceError as exc:
            return ValidationResult(ok=False, message=str(exc))

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        """Return the window's threads that still owe a reply, or raise; never a partial list."""
        if not creds.get("client_json") or not creds.get("refresh_token"):
            raise AuthExpired(AUTH_EXPIRED_MESSAGE)
        now = self._clock.now()
        return await asyncio.to_thread(self._fetch_blocking, creds, window, now)

    async def _validate(self, creds: Mapping[str, str]) -> ValidationResult:
        client_json = creds.get("client_json", "")
        if not client_json:
            return ValidationResult(ok=False, message="Paste the Google OAuth client JSON first")
        config = client_config(client_json)
        if not creds.get("refresh_token"):
            return await self._sign_in_user(config)
        await asyncio.to_thread(self._check_profile, creds)
        return ValidationResult(ok=True, message="Connected to Gmail")

    async def _sign_in_user(self, config: Mapping[str, object]) -> ValidationResult:
        try:
            # The thread cannot be cancelled; run_local_server ends it at the same deadline.
            token = await asyncio.wait_for(
                asyncio.to_thread(self._sign_in, config, SIGN_IN_TIMEOUT_SECONDS),
                self._sign_in_timeout,
            )
        except (TimeoutError, SignInTimedOut):
            return ValidationResult(ok=False, message="Sign-in timed out")
        except SignInFailed:
            return ValidationResult(ok=False, message="Sign-in failed; try Connect again")
        return ValidationResult(
            ok=True, message="Connected to Gmail", updated_creds={"refresh_token": token}
        )

    def _check_profile(self, creds: Mapping[str, str]) -> None:
        with _translated():
            _ = self._service_factory(creds).users().getProfile(userId="me").execute()

    def _fetch_blocking(
        self, creds: Mapping[str, str], window: TimeWindow, now: datetime
    ) -> list[Event]:
        events: list[Event] = []
        with _translated():
            users = self._service_factory(creds).users()
            me = parse(Profile, users.getProfile(userId="me").execute()).emailAddress.lower()
            for thread_id in _thread_ids(users.threads()):
                request = users.threads().get(
                    userId="me", id=thread_id, format="metadata", metadataHeaders=list(HEADERS)
                )
                thread = parse(Thread, request.execute())
                event = owed_event(thread, me, now, self._rules)
                if event is not None and event.start is not None and window.contains(event.start):
                    events.append(event)
        return events


def _thread_ids(threads: _ThreadsApi) -> list[str]:
    ids: list[str] = []
    token: str | None = None
    for _ in range(MAX_PAGES):
        request = threads.list(userId="me", q=QUERY, maxResults=PAGE_SIZE, pageToken=token)
        page = parse(ThreadList, request.execute())
        ids.extend(ref.id for ref in page.threads)
        token = page.nextPageToken
        if token is None:
            return ids
    msg = "Too many recent Gmail threads to scan"
    raise FatalError(msg)


# ---------------------------------------------------------------- credentials and sign-in


def client_config(client_json: str) -> dict[str, object]:
    """Parse the pasted desktop-client file; anything else is a FatalError with a fixed message."""
    try:
        data: object = json.loads(client_json)
        _ = _ClientFile.model_validate(data)
    except (ValueError, ValidationError):
        msg = "That is not a Google OAuth desktop client file; create a Desktop app client"
        raise FatalError(msg) from None
    return cast("dict[str, object]", data)


def default_service(creds: Mapping[str, str]) -> GmailService:
    """Rebuild the credentials from the stored values (no access token is kept) and a service."""
    client = _ClientFile.model_validate(client_config(creds["client_json"])).installed
    credentials = Credentials(  # pyright: ignore[reportUnknownVariableType]  (SDK is untyped)
        token=None,
        refresh_token=creds["refresh_token"],
        token_uri=client.token_uri,
        client_id=client.client_id,
        client_secret=client.client_secret,
        scopes=[SCOPE],
    )
    http = AuthorizedHttp(  # pyright: ignore[reportUnknownVariableType]
        credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)
    )
    return cast("GmailService", build("gmail", "v1", http=http, cache_discovery=False))  # pyright: ignore[reportUnknownArgumentType]


def run_sign_in(config: Mapping[str, object], timeout_seconds: int) -> str:
    """Browser sign-in on a loopback port; returns the refresh token. Runs in a worker thread."""
    try:
        flow = InstalledAppFlow.from_client_config(dict(config), [SCOPE])  # pyright: ignore[reportUnknownMemberType]
        credentials = flow.run_local_server(  # pyright: ignore[reportUnknownMemberType]
            host=LOOPBACK,
            bind_addr=LOOPBACK,
            port=0,
            timeout_seconds=timeout_seconds,
            authorization_prompt_message="",
            access_type="offline",
            prompt="consent",
        )
    except WSGITimeoutError:
        raise SignInTimedOut from None
    except Exception as exc:  # noqa: BLE001  (any vendor failure: only its class is logged)
        logger.warning("gmail sign-in failed: %s", type(exc).__name__)
        raise SignInFailed from None
    token = cast("str | None", credentials.refresh_token)  # pyright: ignore[reportUnknownMemberType]
    if not token:
        raise SignInFailed
    return token


# ---------------------------------------------------------------- error translation


@contextmanager
def _translated() -> Generator[None]:
    """Turn SDK, auth and network failures into SourceErrors with fixed messages."""
    try:
        yield
    except RefreshError as exc:
        if cast("bool", exc.retryable):  # pyright: ignore[reportUnknownMemberType]
            msg = "Google sign-in service is unavailable"
            raise TransientError(msg) from None
        raise AuthExpired(AUTH_EXPIRED_MESSAGE) from None
    except (TransportError, OSError, httplib2.HttpLib2Error):
        msg = "Gmail is unreachable"
        raise TransientError(msg) from None
    except HttpError as exc:
        raise _from_http(exc) from None


class _ErrorReason(BaseModel):
    reason: str = ""


class _ErrorBody(BaseModel):
    errors: list[_ErrorReason] = []


class _ErrorEnvelope(BaseModel):
    error: _ErrorBody = _ErrorBody()


def _from_http(exc: HttpError) -> SourceError:
    status = cast("int", exc.status_code or 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    if status == _UNAUTHORIZED:
        return AuthExpired(AUTH_EXPIRED_MESSAGE)
    if status == _FORBIDDEN and _reason(exc) in _THROTTLE_REASONS:
        return TransientError("Gmail rate limit reached")
    if status in {_TOO_MANY, _NOT_FOUND} or status >= _SERVER_ERROR:
        # 404: a thread deleted between the list and the get; the next sync sees a stable list.
        return TransientError(f"Gmail request failed ({status})")
    if status == _FORBIDDEN:
        return FatalError("Gmail refused the request; check the Gmail API is enabled")
    return FatalError(f"Gmail request failed ({status})")


def _reason(exc: HttpError) -> str:
    """The first error reason in the response body, lower-cased; empty when there is none."""
    try:
        body = _ErrorEnvelope.model_validate_json(exc.content)
    except ValidationError:
        return ""
    return body.error.errors[0].reason.lower() if body.error.errors else ""
