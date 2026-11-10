# 0111. App settings are a small key-value port

Status: accepted

Context: The AI summary opt-in and the summary provider must become changeable from the UI, and the choice has to survive restarts and work on SQLite and Postgres.
Decision: `core/ports.py` gets `AppSettingStore`, a synchronous string-to-string port keyed per user: `get(key, *, user_id="local") -> str | None` and `set(key, value, *, user_id="local")`, which replaces. `storage/sqlite_app_settings.py` implements it over SQLAlchemy with one table `app_settings(user_id, key, value)`, primary key `(user_id, key)`; `create_app_setting_store(database_url)` follows the other stores' URL rules. Values are plain strings (max 500 characters, keys max 100); callers encode booleans and enums.
Alternative: (a) Extend `SecretStore`: settings are not secrets, and the keychain-backed store has no Postgres path and a write-only status API. (b) A config file: not shared across SQLite and Postgres deployments, needs its own parsing and write-back. (c) Environment variables only: not changeable from the UI at runtime.
Reason: One tiny port and one table cover the need on both databases with the same code, keep secrets and settings separate, and keep core free of I/O.
Where: `src/command_center/core/ports.py`, `src/command_center/storage/sqlite_app_settings.py`; `tests/test_app_setting_store_contract.py`, `tests/fakes.py` (`InMemoryAppSettingStore`); `docs/contracts/core.md`, `docs/contracts/storage.md`.
Revisit when: A second setting needs typed values, validation by key, or change history.
