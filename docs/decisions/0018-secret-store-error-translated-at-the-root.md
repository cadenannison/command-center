# 0018. The keychain's error is translated to a services error at the composition root

Status: superseded by 0024

Context: `KeyringSecretStore` raises `SecretStoreError`, which is defined in `adapters/keyring_store.py`. Services must turn it into an error state ("secret store unavailable", no details) but may not import adapters (rule 2), and `core/errors.py` has no class for it and is off limits for this task.
Decision: `services/errors.py` defines `SecretStoreUnavailableError` (no message, no detail). `app.py` wraps the keychain in `GuardedSecretStore`, which catches `SecretStoreError` and raises `SecretStoreUnavailableError` from None. Services catch only the services class.
Alternative: Move `SecretStoreError` into `core/errors.py`, with the adapter importing it from core. That is the cleaner home (it is the secret-store analogue of `AuthExpired`) but it changes core and the keyring adapter, which this card forbids. Catching `Exception` in services was rejected: it would swallow bugs.
Reason: Keeps the import rules intact without touching core, and the wrapper also drops the keychain's own message, which can name a source.
Where: `src/command_center/services/errors.py`; `GuardedSecretStore` in `src/command_center/app.py`; `docs/contracts/services.md`.
Revisit when: Core may change. Then move the class to `core/errors.py`, delete the wrapper, and write a record superseding this one. Any other `SecretStore` implementation must be wrapped the same way until then.
