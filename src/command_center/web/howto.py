"""Step-by-step setup text for each source, shown in a collapsible block on its card.

Taken from docs/sources.md and docs/gmail-setup.md. Where those docs are unsure of a menu path
(the vendors rename menus) the text says "may differ" instead of guessing. Text only: no value of
the user's is ever put into it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HowTo:
    """The steps for one source, plus an optional closing note."""

    steps: tuple[str, ...]
    note: str = ""


HOWTO: dict[str, HowTo] = {
    "canvas": HowTo(
        (
            (
                "In Canvas open Account > Settings > Approved Integrations > New Access Token "
                "(menu names may differ between schools and Canvas versions)."
            ),
            'Give the token a purpose such as "Command Center" and copy it. Canvas shows it once.',
            (
                "Canvas URL: the address of your school's Canvas site, for example "
                "https://school.instructure.com. It must be reachable over HTTPS on a public "
                "address."
            ),
            "Enter the URL and the token here and press Connect.",
        ),
        (
            "Assignments, planner items and calendar events are imported; grades and "
            "announcements are not."
        ),
    ),
    "apple_calendar": HowTo(
        (
            (
                "Sign in at https://account.apple.com, open Sign-In and Security > "
                "App-Specific Passwords and create one (menu names may differ)."
            ),
            (
                "Enter your Apple ID and that app-specific password here, not your normal Apple "
                "password, and press Connect."
            ),
        ),
    ),
    "learningsuite": HowTo(
        (
            (
                "In LearningSuite, copy the iCal (calendar subscription) link of each course. "
                "Where that link is may differ; look for a calendar subscription or iCal option."
            ),
            "Paste the links here, one per line, and press Connect. They are treated as secrets.",
            (
                "If it connects but shows no items, run `uv run command-center diagnose "
                "learningsuite`; docs/first-run.md explains each answer."
            ),
        ),
    ),
    "gmail": HowTo(
        (
            "Open https://console.cloud.google.com/ and create a project (any name).",
            'APIs & Services > Library > search "Gmail API" > Enable.',
            (
                "APIs & Services > OAuth consent screen (Google Auth platform > Branding/Audience "
                "in the newer UI; menus may differ). User type External, leave the publishing "
                "status as Testing, and add your own Gmail address under Test users. Without that "
                "Google refuses the sign-in."
            ),
            (
                "APIs & Services > Credentials > Create credentials > OAuth client ID, application "
                "type Desktop app. Download the JSON file or copy its contents."
            ),
            (
                "Paste the whole JSON here and press Connect. Your browser opens; choose your "
                "account and allow read-only access. Google may warn that the app is unverified: "
                "that is expected for your own client, choose Continue."
            ),
        ),
        (
            "While the consent screen is in Testing, Google expires the sign-in every 7 days; the "
            "card then shows Reconnect. docs/gmail-setup.md lists fixes for common errors."
        ),
    ),
    "weather": HowTo(
        (
            (
                "Enter the latitude and longitude of the place you want a forecast for, for "
                "example 40.2338 and -111.6585."
            ),
            "Forecasts come from Open-Meteo and need no account.",
        ),
    ),
    "gemini": HowTo(
        (
            (
                "Create a key in Google AI Studio: https://aistudio.google.com/apikey (the page "
                "layout may differ)."
            ),
            (
                "Enter it here and press Connect. It is checked with one small request to Gemini "
                "before it is stored, and works at once without a restart."
            ),
            (
                "A key alone does not turn summaries on: "
                "use the Enable button on the Today summary card."
            ),
        ),
    ),
}


def howto_for(source: str) -> HowTo | None:
    """The steps for source, or None when it has none."""
    return HOWTO.get(source)
