# 0024. SecretStoreError lives in core; the wrapper is gone

Status: accepted (supersedes 0018)

Context: Decision 0018 kept the keychain's `SecretStoreError` in the adapter because core was off limits, and translated it to a services class through `GuardedSecretStore` in `app.py`. The project manager has now allowed the move.
Decision: `SecretStoreError` is defined in `core/errors.py` (not a `SourceError`; its message says why, never a secret value). `adapters/keyring_store.py` imports and re-exports it, so existing imports keep working. `GuardedSecretStore` and `SecretStoreUnavailableError` are deleted. Services catch `core.errors.SecretStoreError` directly and report the fixed text `secret store unavailable`, never the error's own message.
Alternative: Keep the wrapper. Rejected: it was only there to avoid touching core, and it made every other `SecretStore` implementation responsible for wrapping itself.
Reason: One error class in the place both layers may import, one fewer class to wrap, and no behaviour change for callers: the detail still never leaves the service.
Where: `src/command_center/core/errors.py`; `src/command_center/adapters/keyring_store.py`; `src/command_center/services/sync.py` and `settings.py`; `docs/contracts/core.md`, `services.md`, `adapters.md`; `docs/MAP.md`.
Revisit when: A second secret store (for example a server-side vault) needs its own failure classes.
