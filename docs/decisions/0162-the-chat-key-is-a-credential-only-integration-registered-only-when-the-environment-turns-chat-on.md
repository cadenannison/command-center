# 0162. The chat API key is a credential-only integration, registered only when the environment turns chat on

Status: superseded by 0170 (the registration rule only; the key handling stands)

Context: An OpenAI-compatible server may need a key (OpenRouter, OpenAI). It must live in the keychain (rule 5) and be write-only through the settings API, like the Gemini key (decisions 0100-0106). Always registering a `chat` integration adds a source to `GET /v1/settings`, and three existing tests assert the exact set of integrations.
Decision: `adapters/chat_openai.py` has `ChatKeyIntegration`: name `chat`, one secret field `api_key`, and it validates only that a key was given (the server is not called to check it). `app.py` registers it only when `CC_CHAT_ENABLED` is set. The provider reads the key from the secret store on each call and sends it as a Bearer header; it is in no URL, log line or error text, and a provider error carries a fixed sentence by status code (401/403, 404, 429/503, other 4xx and 5xx), never the server's body. Ollama needs no key; Gemini uses the existing `gemini` credential.
Alternative: Register the integration always (needs edits to three existing tests, which this task may not make: `tests: new-only`); a key field on the chat settings route (a second secret path outside the keychain contract).
Reason: Avoids editing existing tests and keeps a user who never turns chat on from seeing a source they cannot use.
Where: `src/command_center/adapters/chat_openai.py`, `app.py`; `tests/test_app_chat.py`, `tests/test_chat_adapters.py`.
Revisit when: The chat settings UI is built; register the integration always in the same change that updates those tests, with the project manager's permission.
