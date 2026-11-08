"""GmailAdapter.validate, sign-in, credential rebuilding and error translation."""

import threading
from collections.abc import Mapping
from typing import Any, cast

import pytest
from google.auth.exceptions import RefreshError, TransportError
from google_auth_httplib2 import AuthorizedHttp  # pyright: ignore[reportMissingTypeStubs]

from command_center.adapters import gmail
from command_center.adapters.gmail import GmailAdapter, SignInFailed, SignInTimedOut
from command_center.core.errors import AuthExpired, FatalError, TransientError
from fakes import FakeClock
from gmail_support import (
    CLIENT_JSON,
    CREDS,
    NOW,
    WINDOW,
    FakeGmail,
    http_error,
    make_adapter,
)

NO_TOKEN = {"client_json": CLIENT_JSON}


def signing_in(token: str = "fake-new-refresh-token") -> gmail.SignIn:  # noqa: S107
    def sign_in(_config: Mapping[str, object], _timeout: int) -> str:
        return token

    return sign_in


def adapter_with(sign_in: gmail.SignIn, *, timeout: float = 180) -> GmailAdapter:
    return GmailAdapter(
        FakeClock(NOW),
        service_factory=lambda _creds: FakeGmail(),
        sign_in=sign_in,
        sign_in_timeout=timeout,
    )


# ---------------------------------------------------------------- expired tokens


async def test_an_expired_refresh_token_in_fetch_is_auth_expired() -> None:
    fake = FakeGmail(profile=RefreshError("invalid_grant: Token has been expired or revoked."))

    with pytest.raises(AuthExpired) as raised:
        await make_adapter(fake).fetch(CREDS, WINDOW)

    assert "invalid_grant" not in str(raised.value)
    assert raised.value.__cause__ is None


async def test_a_401_from_gmail_is_auth_expired() -> None:
    with pytest.raises(AuthExpired):
        await make_adapter(FakeGmail(profile=http_error(401))).fetch(CREDS, WINDOW)


async def test_a_refresh_error_marked_retryable_is_transient() -> None:
    fake = FakeGmail(profile=RefreshError("token endpoint down", retryable=True))

    with pytest.raises(TransientError):
        await make_adapter(fake).fetch(CREDS, WINDOW)


async def test_validate_reports_an_expired_token_as_a_failed_check() -> None:
    fake = FakeGmail(profile=RefreshError("invalid_grant"))

    result = await make_adapter(fake).validate(CREDS)

    assert not result.ok
    assert result.message == gmail.AUTH_EXPIRED_MESSAGE
    assert result.updated_creds is None


# ---------------------------------------------------------------- other errors


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (http_error(429), TransientError),
        (http_error(503), TransientError),
        (http_error(403, "rateLimitExceeded"), TransientError),
        (http_error(403, "accessNotConfigured"), FatalError),
        (http_error(400), FatalError),
        (TimeoutError("timed out"), TransientError),
        (TransportError("no route"), TransientError),
    ],
)
async def test_failures_are_translated(failure: Exception, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        await make_adapter(FakeGmail(profile=failure)).fetch(CREDS, WINDOW)


async def test_a_translated_error_never_carries_the_vendor_message() -> None:
    with pytest.raises(TransientError) as raised:
        await make_adapter(FakeGmail(profile=OSError("fake-refresh-token leaked"))).fetch(
            CREDS, WINDOW
        )

    assert "fake-refresh-token" not in str(raised.value)


# ---------------------------------------------------------------- validate


async def test_validate_with_a_refresh_token_calls_get_profile_and_keeps_the_token() -> None:
    fake = FakeGmail()

    result = await make_adapter(fake).validate(CREDS)

    assert result.ok
    assert result.updated_creds is None
    assert fake.profile_calls == 1


async def test_validate_without_a_client_file_asks_for_it() -> None:
    result = await make_adapter(FakeGmail()).validate({})

    assert not result.ok
    assert "client JSON" in result.message


async def test_validate_rejects_a_client_file_that_is_not_a_desktop_client() -> None:
    web_client = '{"web": {"client_id": "fake-id", "client_secret": "fake-secret"}}'

    result = await make_adapter(FakeGmail()).validate({"client_json": web_client})

    assert not result.ok
    assert "Desktop app" in result.message
    assert "fake-secret" not in result.message


# ---------------------------------------------------------------- sign-in


async def test_a_successful_sign_in_returns_the_refresh_token_to_store() -> None:
    result = await adapter_with(signing_in("fake-new-refresh-token")).validate(NO_TOKEN)

    assert result.ok
    assert result.updated_creds == {"refresh_token": "fake-new-refresh-token"}
    assert "fake-new-refresh-token" not in repr(result)


async def test_a_sign_in_that_runs_past_the_deadline_times_out() -> None:
    release = threading.Event()

    def stuck(_config: Mapping[str, object], _timeout: int) -> str:
        release.wait(timeout=10)
        return "fake-late-token"

    try:
        result = await adapter_with(stuck, timeout=0.01).validate(NO_TOKEN)
    finally:
        release.set()

    assert not result.ok
    assert result.message == "Sign-in timed out"
    assert result.updated_creds is None


async def test_a_sign_in_that_gives_up_on_its_own_also_times_out() -> None:
    def gave_up(_config: Mapping[str, object], _timeout: int) -> str:
        raise SignInTimedOut

    result = await adapter_with(gave_up).validate(NO_TOKEN)

    assert result.message == "Sign-in timed out"


async def test_a_failed_sign_in_is_reported_without_detail() -> None:
    def denied(_config: Mapping[str, object], _timeout: int) -> str:
        raise SignInFailed

    result = await adapter_with(denied).validate(NO_TOKEN)

    assert not result.ok
    assert result.message == "Sign-in failed; try Connect again"


class FakeFlow:
    """InstalledAppFlow stand-in: records how the browser flow was started."""

    outcome: object = None
    calls: list[dict[str, object]] = []  # noqa: RUF012  (shared with the test on purpose)
    scopes: list[str] = []  # noqa: RUF012

    class Credentials:
        refresh_token: str | None = "fake-flow-refresh-token"  # noqa: S105

    @classmethod
    def from_client_config(cls, _config: Mapping[str, object], scopes: list[str]) -> "FakeFlow":
        cls.scopes = scopes
        return cls()

    def run_local_server(self, **kwargs: object) -> "FakeFlow.Credentials":
        type(self).calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.Credentials()


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch) -> type[FakeFlow]:
    FakeFlow.calls = []
    FakeFlow.outcome = None
    FakeFlow.Credentials.refresh_token = "fake-flow-refresh-token"  # noqa: S105
    monkeypatch.setattr(gmail, "InstalledAppFlow", FakeFlow)
    return FakeFlow


def test_the_browser_flow_asks_for_read_only_offline_access_with_a_timeout(
    flow: type[FakeFlow],
) -> None:
    token = gmail.run_sign_in({"installed": {}}, gmail.SIGN_IN_TIMEOUT_SECONDS)

    assert token == "fake-flow-refresh-token"  # noqa: S105
    assert flow.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
    [call] = flow.calls
    assert call["timeout_seconds"] == 180
    assert call["port"] == 0
    assert call["host"] == call["bind_addr"] == "127.0.0.1"
    assert call["access_type"] == "offline"
    assert call["prompt"] == "consent"


def test_the_browser_flow_timing_out_is_reported_as_a_timeout(flow: type[FakeFlow]) -> None:
    flow.outcome = gmail.WSGITimeoutError("timed out")

    with pytest.raises(SignInTimedOut):
        gmail.run_sign_in({}, 180)


def test_a_flow_that_returns_no_refresh_token_fails(flow: type[FakeFlow]) -> None:
    flow.Credentials.refresh_token = None

    with pytest.raises(SignInFailed):
        gmail.run_sign_in({}, 180)


def test_any_other_flow_failure_is_a_sign_in_failure(flow: type[FakeFlow]) -> None:
    flow.outcome = OSError("address in use")

    with pytest.raises(SignInFailed):
        gmail.run_sign_in({}, 180)


# ---------------------------------------------------------------- credentials


def test_each_service_is_rebuilt_from_the_stored_values_without_an_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, object] = {}

    def fake_build(service: str, version: str, **kwargs: object) -> object:
        built.update(service=service, version=version, **kwargs)
        return object()

    monkeypatch.setattr(gmail, "build", fake_build)

    _ = gmail.default_service(CREDS)

    assert (built["service"], built["version"], built["cache_discovery"]) == ("gmail", "v1", False)
    assert isinstance(built["http"], AuthorizedHttp)
    http = cast("Any", built["http"])
    credentials = http.credentials
    assert credentials.token is None
    assert credentials.refresh_token == "fake-refresh-token"  # noqa: S105
    assert credentials.client_id == "fake-client-id.apps.example.com"
    assert list(credentials.scopes) == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert http.http.timeout == gmail.HTTP_TIMEOUT_SECONDS
