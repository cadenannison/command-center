# 0170. The chat key integration is always registered

Status: accepted. Supersedes the registration rule of 0162.

Context: Decision 0162 registered the `chat` integration only when `CC_CHAT_ENABLED` was set, to avoid editing three existing tests that list the integrations. The project manager approved the always-registered form and the test edits.
Decision: `build_integrations` in `app.py` always returns `gemini` and `chat`, so `GET /v1/settings` lists a `chat` source with `keys: {}` until a key is stored. Everything else in 0162 stands: one secret field `api_key`, validation only that it is not blank, the key read from the secret store on each call. Existing assertions changed under the project manager's `allow-test-edits` permission, those lines only: `tests/test_app_integrations.py` (the listed sources and the set of integrations) and `tests/test_app_wiring.py` (the expected settings rows).
Alternative: Keep it conditional on the environment (a user who turns chat on in a future settings page would need a restart to see the key field).
Reason: The key must be enterable before chat is turned on, and the settings page, not the environment, will turn it on.
Where: `src/command_center/app.py` (`build_integrations`); `tests/test_app_chat.py`, `tests/test_app_integrations.py`, `tests/test_app_wiring.py`.
Revisit when: The web settings card for `chat` is built. `web/sources.py` has no `SOURCE_FORMS["chat"]` yet, so the card falls back to a bare label with no fields (the web session's change; it should be `credential_only`).
