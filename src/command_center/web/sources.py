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
        (_field("gmail", "client_json", "OAuth client JSON", multiline=True),),
        sign_in_wait=True,
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
