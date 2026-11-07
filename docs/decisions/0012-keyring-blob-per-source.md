# 0012. The keychain adapter stores one blob per (user, source)

Status: accepted. Supersedes the adapter clause in the Consequences of 0010.

Context: 0010 made the `SecretStore` interface per-field and said the keychain adapter "must store one entry per key and track the key set for `get`/`delete`". That needs an index entry that can disagree with the key entries, and a crash between writing them leaves a key that `get` and `delete` cannot find.
Decision: `KeyringSecretStore` keeps one keychain entry per (user, source) holding a JSON object of key to value. The interface stays per-key exactly as 0010 defines it: `set(source, key, value)`, `get`, `status` per key, `delete` removing every key. A process-wide lock covers the read-modify-write in `set` and the `delete`, so threads in one process cannot lose each other's updates.
Reason: One entry has no index to drift, and `delete` removes the whole source in one call. A threaded app (FastAPI's threadpool, workers) is the realistic source of concurrent `set`, and a lock closes that.
Consequences: The lock does not protect against a second process writing the same source; single user, single Mac makes that unlikely, and distributed mode must settle secrets separately (0007). One corrupt entry hides every key of its source: `get`, `status` and `set` raise `SecretStoreError`, and `delete` of the source removes the corrupt entry so the keys can be entered again. A source's secrets must fit one keychain entry; OAuth client id, secret and refresh token do. The core `SecretStore` contract and `secret_status` are unchanged.
