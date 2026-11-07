# 0007. Secrets live in the OS keychain

Status: accepted

Context: Tokens and app passwords must not sit in files, the database or logs.
Decision: Store secrets with keyring (macOS Keychain). The settings API is write-only: status is `set` plus the last 4 characters. The server binds 127.0.0.1.
Consequences: keyring is imported only in `adapters/keyring_store.py`; `core` forbids it. Tests use an in-memory secret store through the port. Distributed mode must pass secrets by an explicit mechanism, to be decided when it is built.
