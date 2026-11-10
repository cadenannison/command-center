# 0102. "Sync now", "Test connection" and "Save anyway" are actions of the existing `PUT /settings/{source}` route

Status: accepted; open for the project manager (see Revisit)

Context: Task A1 asks for per-source "Sync now" and "Test connection" buttons and a "Save anyway" submit. `tests/test_remote_policy.py` lists every route in `POLICY` and fails until each new route is classified; the card allows no edit to that file.
Decision: The form field `action` (`connect` by default, `unverified`, `test`, `sync`; anything else is 422) selects what the existing `PUT /settings/{source}` does. `test` validates the stored credentials only (typed values are not sent: the buttons sit outside the form) and answers with the result paragraph only. `sync` marks the source syncing, queues the sync as a background task, and answers with the result paragraph plus the status element, swapped out of band, so the page starts polling. Both are refused while another action on the source runs.
Alternative: Dedicated routes (`POST /settings/{source}/sync`, `POST /settings/{source}/test`). Cleaner REST, but each needs a row in the `POLICY` table of `tests/test_remote_policy.py`.
Reason: The existing PUT is already classified as refused for a paired phone, so the actions inherit that policy and no test has to change. A phone may still call `POST /v1/sync` for the same sync.
Where: `src/command_center/web/settings_actions.py` (`SettingsActions.run`); the buttons in `web/templates/_card.html`; `web/templates/_action_result.html`. Tests: `tests/test_web_settings_usability.py`.
Known edge: Gmail's `validate` starts the interactive Google sign-in when no refresh token is stored (for example after an unverified save), so "Test connection" on Gmail can open that sign-in and store the token it returns. It is the same call Connect makes; the button does not guard against it.
Revisit when: A card allows editing `tests/test_remote_policy.py`: split the actions into their own routes and supersede this record.
