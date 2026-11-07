# 0004. AI summaries are opt-in and redacted

Status: accepted

Context: Summaries send personal data to a third party. Gemini's free tier may be used to train Google models.
Decision: Summaries are OFF by default. When on, only titles, due dates and trimmed subjects are sent, with addresses and numbers stripped; never email bodies. A flag excludes email entirely. Providers are Gemini and a local Ollama option.
Consequences: Redaction lives in `core` and runs before any provider (property-tested: it never leaks). The settings UI states the training caveat next to the Gemini choice. Providers are adapters, one SDK file each.
Sources (checked 2026-11-07): https://ai.google.dev/terms (it redirects to https://aistudio.google.com/docs/terms) supports the free-tier caveat. For the unpaid tier it says Google uses the content you submit and the responses "to provide, improve, and develop" its products, and that human reviewers may read, annotate and process input and output; for the paid tier it says Google does not use prompts or responses to improve its products. The wording is "improve and develop", not the word "train" used in the Context above.
