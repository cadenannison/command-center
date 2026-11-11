"""What the settings page asks for, per source. Labels and field kinds only; never values."""

from dataclasses import dataclass

from command_center.services.credential_fields import is_secret

MAX_VALUE_LENGTH = 8192  # same bound as the API's CredentialValue

GEMINI_CAVEAT = (
    "On Gemini's free tier Google may use what you send to improve its products, and human "
    "reviewers may read it. Only titles, due dates and trimmed subjects are sent, with email "
    "addresses and numbers redacted first, never email bodies. Saving a key does not turn "
    "summaries on; that is the CC_SUMMARY_ENABLED setting."
)


GMAIL_NOTE = (
    "Command Center only reads your mail, to find replies you owe. It never sends, deletes or "
    "changes anything, and it does not read message bodies. What you paste below is stored only "
    "on this computer, never in the project folder or any file you commit, and is never shown "
    "again after you save it."
)
GMAIL_WAITING = (
    "Waiting for Google sign-in… A Google page should have opened in your browser: choose your "
    "account and allow read-only access, then come back here. This usually takes about a minute; "
    "it gives up after 3 minutes."
)
GMAIL_SYNCING = "Checking your recent mail now; this takes under a minute."


@dataclass(frozen=True)
class PendingHelp:
    """What a card not yet connected says: now, next steps, how long, and what success shows."""

    now: str
    steps: tuple[str, ...]
    time: str
    result: str


GMAIL_PENDING = PendingHelp(
    now=(
        "Gmail is not connected yet. Nothing is read from your mail until you finish the steps "
        "below."
    ),
    steps=(
        (
            "Open “How to connect Gmail” below and follow it to get a credentials file from "
            "Google. Do this once."
        ),
        "Copy the whole file, paste it into the box, and press Connect.",
        (
            "A Google page opens in your browser. Choose your account and allow read-only "
            "access, then come back to this page."
        ),
    ),
    time=(
        "The first time takes about 5 minutes. After you press Connect, the Google page waits "
        "for up to 3 minutes; if it runs out, press Connect again."
    ),
    result=(
        "When it works, this card says “Connected” and shows when Command Center last checked "
        "your mail."
    ),
)


@dataclass(frozen=True)
class Field:
    """One input of a source's form. `secret` comes from `credential_fields`, never from here."""

    key: str
    label: str
    secret: bool = False
    multiline: bool = False
    hint: str = ""


@dataclass(frozen=True)
class SourceForm:
    """The form of one source."""

    label: str
    fields: tuple[Field, ...]
    note: str = ""
    sign_in_wait: bool = False  # connect blocks on a browser sign-in and can take minutes
    credential_only: bool = False  # an API key: no sync, no items, so no sync state to show
    city_search: bool = False  # the card has a "Find a city" box that fills its two coordinates
    waiting: str = ""  # the busy line while a connect runs; empty means "Connecting…"
    pending: PendingHelp | None = None  # shown while nothing is stored and no sync has run
    syncing_note: str = ""  # shown under the status while any sync runs


def _field(source: str, key: str, label: str, *, multiline: bool = False, hint: str = "") -> Field:
    return Field(key, label, secret=is_secret(source, key), multiline=multiline, hint=hint)


SOURCE_FORMS: dict[str, SourceForm] = {
    "canvas": SourceForm(
        "Canvas",
        (
            _field("canvas", "base_url", "Canvas URL", hint="https://school.instructure.com"),
            _field("canvas", "token", "Access token"),
        ),
    ),
    "apple_calendar": SourceForm(
        "Apple Calendar",
        (
            _field("apple_calendar", "username", "Apple ID"),
            _field("apple_calendar", "app_password", "App-specific password"),
        ),
    ),
    "learningsuite": SourceForm(
        "LearningSuite",
        (
            _field(
                "learningsuite", "urls", "iCal feed URLs", multiline=True, hint="One URL per line"
            ),
        ),
    ),
    "gmail": SourceForm(
        "Gmail",
        (
            _field(
                "gmail", "client_json", "Google credentials (paste the whole file)", multiline=True
            ),
        ),
        note=GMAIL_NOTE,
        sign_in_wait=True,
        waiting=GMAIL_WAITING,
        pending=GMAIL_PENDING,
        syncing_note=GMAIL_SYNCING,
    ),
    "weather": SourceForm(
        "Weather",
        (
            _field("weather", "latitude", "Latitude", hint="40.2338"),
            _field("weather", "longitude", "Longitude"),
        ),
        city_search=True,
    ),
    "gemini": SourceForm(
        "Gemini summaries",
        (_field("gemini", "api_key", "API key"),),
        note=GEMINI_CAVEAT,
        credential_only=True,
    ),
    "chat": SourceForm(
        "Chat provider key",
        (_field("chat", "api_key", "API key"),),
        credential_only=True,
    ),
}


def form_for(source: str) -> SourceForm:
    """The form of source; a registered source without a known form gets a label and no fields."""
    return SOURCE_FORMS.get(source, SourceForm(source, ()))
