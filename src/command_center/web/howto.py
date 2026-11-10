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
            (
                "Or type a city under Find a city and press Search: pick the right match from the "
                "list and the two boxes fill in (you can still edit them). Nothing is saved until "
                "you press Connect."
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
    "chat": HowTo(
        (
            (
                "This is the API key for the chat provider you choose, for example OpenRouter or "
                "OpenAI. Create one in that provider's account (the page layout may differ)."
            ),
            (
                "Hosted providers need a key. Local providers such as Ollama, LM Studio or "
                "llama.cpp on this machine or your network need none: leave this empty."
            ),
            (
                "Enter the key here and press Connect. It is kept in your keychain and never "
                "shown again, only its last four characters."
            ),
        ),
        (
            "Saving a key does not turn chat on or choose a provider. Chat with Gemini uses the "
            "Gemini key above, not this one."
        ),
    ),
}


def howto_for(source: str) -> HowTo | None:
    """The steps for source, or None when it has none."""
    return HOWTO.get(source)


# The AI settings card's guides, one per provider (decision 0202). Titles are what the summary says.
AI_HOWTOS: tuple[tuple[str, HowTo], ...] = (
    (
        "Ollama",
        HowTo(
            (
                (
                    "Install Ollama from https://ollama.com and start it. It answers on this Mac "
                    "at http://localhost:11434."
                ),
                (
                    "In a terminal run `ollama pull llama3.2` (or another model; `ollama list` "
                    "shows the names you have)."
                ),
                (
                    "Here choose the provider Ollama, leave the address empty or enter "
                    "http://localhost:11434, and enter the model name as `ollama list` shows it."
                ),
                "Save, then press Test connection. No key is needed.",
            ),
            (
                "Ollama on another computer works too, but Ollama listens only on 127.0.0.1 (this "
                "computer) by default, so another computer needs OLLAMA_HOST set on that computer. "
                "On it, set OLLAMA_HOST=0.0.0.0:11434 and restart Ollama (on a Mac: quit the app, "
                "run `launchctl setenv OLLAMA_HOST 0.0.0.0:11434`, open it again; with systemd: "
                "add the variable to the service), and allow port 11434 through its firewall. "
                "Then enter its address here, for example http://192.168.1.20:11434. Plain http is "
                "allowed only for this Mac and your own network. Over plain http on a LAN, your "
                "agenda text crosses the network unencrypted and anyone on that network can reach "
                "the server: use it only on a network you trust. Keep the address free of keys; "
                "Ollama needs none."
            ),
        ),
    ),
    (
        "LM Studio or llama.cpp",
        HowTo(
            (
                (
                    "LM Studio: load a model, open the Developer tab and start the local server "
                    "(it answers at http://localhost:1234/v1; menu names may differ). llama.cpp: "
                    "run `llama-server -m your-model.gguf --port 8080`, which answers at "
                    "http://localhost:8080/v1."
                ),
                (
                    "Here choose the provider OpenAI-compatible server and enter that address, "
                    "including the /v1 at the end."
                ),
                "Enter the model name the server lists (llama.cpp accepts any name).",
                "Save, then press Test connection.",
            ),
            (
                "These servers need no key. If yours does, enter it on the Chat provider key "
                "card; it is sent only over https or to this Mac, never in clear text across "
                "your network."
            ),
        ),
    ),
    (
        "Gemini",
        HowTo(
            (
                "Choose the provider Gemini and leave the address empty.",
                (
                    "Chat with Gemini uses the key on the Gemini summaries card; add it there if "
                    "you have not (https://aistudio.google.com/apikey, the page layout may "
                    "differ)."
                ),
                (
                    "The model can stay empty to use the built-in default. Save, then press Test "
                    "connection."
                ),
            ),
            (
                "On Gemini's free tier Google may use what you send to improve its products. "
                "With Gemini the chat sends your agenda text (titles and due dates, redacted) to "
                "Google."
            ),
        ),
    ),
)
