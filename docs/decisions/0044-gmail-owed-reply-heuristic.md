# 0044. Gmail owed-reply heuristic: choices the card left open

Status: accepted

Context: Task 2c fixes the rule (no AI): keep a thread when its last message is from someone else, is not bulk, and the user is in To or the thread is starred or important. It leaves several details open, and names `vip_senders` and `muted_senders` without saying what a VIP changes.
Decision:
- A VIP sender counts like starred or important: the thread is kept even when the user is only copied. A muted sender is dropped before anything else. Entries are exact addresses or `@domain`, matched case-insensitively.
- Bulk also covers `Precedence: list` and `junk` (RFC 2076 values beside `bulk`), an `Auto-Submitted` header other than `no` (RFC 3834), and a sender whose local part contains `noreply`, `no-reply`, `do-not-reply` or `donotreply`.
- "Starred or important" is a label on any message of the thread. "From someone else" means no `SENT` label and a From address that is not the account's (from `users.getProfile`, one extra call per fetch). A message labelled `DRAFT` is ignored when finding the last message, so an unsent draft does not hide a thread that still waits.
- Waiting is measured from the last message's `internalDate` to the clock; strictly more than 2 days is `overdue`.
- The link is `https://mail.google.com/mail/u/0/#all/<thread id>`, not `u/<address>`, so no address is stored. `raw` is `{"sender": <display name>, "snippet": <last message snippet, HTML-unescaped, passed through `core.redact` (addresses become `[email]`, long digit groups `[number]`), then 200 chars>}`, because a snippet is the start of the body and the card says `raw` never holds an address; a display name that contains `@` is stored as `""`. Subjects are decoded from RFC 2047 and trimmed to 120 characters.
- Events are kept only when `start` is in the sync window. The query is `newer_than:14d`, so owed threads older than 14 days leave the store at the next sync (the horizon looks back 14 days too).
- Up to 20 pages of 100 threads are listed; more raises `FatalError` rather than returning a partial list. Threads are fetched one after another. A 404 on `threads.get` (deleted between list and get) is `TransientError`; 401 is `AuthExpired`; 429, 5xx and throttling 403s are `TransientError`; other 4xx are `FatalError`.
- `validate` with a refresh token calls `users.getProfile`, which makes google-auth refresh the access token; it does not refresh explicitly. After a browser sign-in it returns `ok` with `updated_creds` and makes no further call. The sign-in asks for `access_type=offline` and `prompt=consent` so Google returns a refresh token, and prints nothing (`authorization_prompt_message=""`). The local sign-in server binds and redirects on `127.0.0.1` only.
- Every HTTP call goes through `httplib2.Http(timeout=15)` wrapped in `google_auth_httplib2.AuthorizedHttp`. Both are installed dependencies of `google-api-python-client` (in `uv.lock`) but are not listed in `pyproject.toml`.
Alternative: A VIP that bypasses the bulk rules; `Precedence: bulk` only; `u/<address>` links; a global socket timeout.
Reason: Each choice errs toward showing fewer, more certain items, and keeps addresses out of stored data.
Where: `src/command_center/adapters/gmail_mail.py`, `src/command_center/adapters/gmail.py`, `tests/test_gmail_adapter.py`, `tests/test_gmail_auth.py`.
Revisit when: the owed list shows false positives or misses, a user has aliases (addressed-to uses only the account address), or a Workspace account needs a longer look-back.
