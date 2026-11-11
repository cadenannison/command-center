# Engineering standards

Read by section; each is short on purpose. Lint, types and import contracts enforce what they can.

## Time, randomness, ids
`core` and `services` never call the clock, RNG or uuid. They take `Clock`, `Rng`, `IdSource`
(`core/ports.py`). Composition roots and adapters pass the real ones. Tests pass fakes.

## Ports and adapters
A new integration is: a Protocol in `core/ports.py`, a service that uses it, an adapter file that
implements it (the only importer of its vendor SDK), and a wiring line in a composition root.

## Boundaries and validation
Everything crossing a boundary (HTTP in, HTTP out, DB rows, feed contents) is parsed into a pydantic
model first. Treat feed and API content as untrusted: bound sizes, tolerate missing fields, never eval.

## Errors
One exception class per failure class (auth rejected, rate limited, unreachable, malformed). Adapters
translate vendor errors into these. The UI shows state per source ("Reconnect", "Last synced 3h ago"),
not stack traces.

## Network
Every outbound call has a timeout. Retries need a failure class, a cap, backoff and a logged reason.
Only idempotent reads are retried.

## Secrets and privacy
Secrets: behind the secret-store port: the OS keychain through the keyring adapter by default, a protected file under Docker. The settings API is write-only. Logs carry no tokens,
addresses, subjects or event titles at INFO and above. AI summaries follow `docs/decisions/0004-summaries.md`.

## API
Paths are `/v1/...`. Changing or removing one is a breaking change for the mobile repo: add a new path
or field and deprecate the old one. Rebuild `docs/generated/` in the same change.

## Tests
See `.claude/rules/tests.md`. Humans own test intent: an agent writes the implementation against a test
the human wrote or reviewed.
