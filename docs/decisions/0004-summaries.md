# 0004. AI summaries are opt-in and redacted

Status: accepted

Context: Summaries send personal data to a third party. Gemini's free tier may be used to train Google models.
Decision: Summaries are OFF by default. When on, only titles, due dates and trimmed subjects are sent, with addresses and numbers stripped; never email bodies. A flag excludes email entirely. Providers are Gemini and a local Ollama option.
Consequences: Redaction lives in `core` and runs before any provider (property-tested: it never leaks). The settings UI states the training caveat next to the Gemini choice. Providers are adapters, one SDK file each.
