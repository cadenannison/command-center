"""What the settings page asks for, per source. Labels and field kinds only; never values."""

from dataclasses import dataclass

MAX_VALUE_LENGTH = 8192  # same bound as the API's CredentialValue

GEMINI_CAVEAT = (
    "On Gemini's free tier Google may use what you send to improve its products, and human "
    "reviewers may read it. Only titles, due dates and trimmed subjects are sent, with email "
    "addresses and numbers redacted first, never email bodies. Saving a key does not turn "
    "summaries on; that is the CC_SUMMARY_ENABLED setting."
)


@dataclass(frozen=True)
class Field:
    """One input of a source's form."""

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


SOURCE_FORMS: dict[str, SourceForm] = {
    "canvas": SourceForm(
        "Canvas",
        (
            Field("base_url", "Canvas URL", hint="https://school.instructure.com"),
            Field("token", "Access token", secret=True),
        ),
    ),
    "apple_calendar": SourceForm(
        "Apple Calendar",
        (
            Field("username", "Apple ID"),
            Field("app_password", "App-specific password", secret=True),
        ),
    ),
    "learningsuite": SourceForm(
        "LearningSuite",
        (Field("urls", "iCal feed URLs", secret=True, multiline=True, hint="One URL per line"),),
    ),
    "gmail": SourceForm(
        "Gmail",
        (Field("client_json", "OAuth client JSON", secret=True, multiline=True),),
        sign_in_wait=True,
    ),
    "weather": SourceForm(
        "Weather",
        (Field("latitude", "Latitude", hint="40.2338"), Field("longitude", "Longitude")),
    ),
    "gemini": SourceForm(
        "Gemini summaries",
        (Field("api_key", "API key", secret=True),),
        note=GEMINI_CAVEAT,
        credential_only=True,
    ),
}


def form_for(source: str) -> SourceForm:
    """The form of source; a registered source without a known form gets a label and no fields."""
    return SOURCE_FORMS.get(source, SourceForm(source, ()))
