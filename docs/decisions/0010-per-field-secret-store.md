# 0010. SecretStore is keyed per field

Status: accepted. The adapter clause of the Consequences is superseded by 0012 (one blob per source); the interface below is unchanged.

Context: A source can need several secrets (CalDAV username plus app password, an OAuth client id, secret and refresh token). One string per source forced callers to pack them into JSON, which hides which field is set and breaks "last 4 characters" status.
Decision: `SecretStore` stores one value per (user, source, key): `set(source, key, value)`, `get(source) -> Mapping[str, str]`, `status(source) -> Mapping[str, SecretStatus]`, `delete(source)` removes every key of the source. `SecretStatus.last4` is None for values shorter than 8 characters.
Reason: Status and replacement work per field, and adapters receive the `Mapping` they already take as `creds`. Hiding last4 on short values keeps the status from revealing most of a short secret.
Consequences: The keychain adapter must store one entry per key and track the key set for `get`/`delete`. Core exposes `secret_status(value)` so every store applies the same rule. Refines 0007.
