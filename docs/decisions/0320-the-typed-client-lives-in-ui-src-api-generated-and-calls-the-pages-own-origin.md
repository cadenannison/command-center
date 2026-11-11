# 0320. The typed client lives in ui/src/api/generated/ and calls the page's own origin

Status: accepted

Context: Task P1b says to generate `ui/src/api/schema.d.ts`. Decision 0300 names `ui/src/api/generated/` as the directory of the generated client, and `eslint.config.js`, the "never hand-edited" rule in AGENTS.md and the new `gen-check` all key on that directory. The client must be same-origin (0300, 0301 item 7), and openapi-fetch builds a `Request`, which rejects a relative URL outside a browser (jsdom and Node).
Decision:
- The generated file is `ui/src/api/generated/schema.d.ts` (the card's file name, 0300's directory). `ui/package.json` has `"gen": "openapi-typescript ../docs/generated/openapi.json -o src/api/generated/schema.d.ts"`; `mise run ui:gen` runs it. `bash scripts/ui.sh gen-check` (in `p1b-guard.patch`, run by `ui:check` and CI) regenerates to a temp file and fails on any difference, so a hand edit or a stale file is caught.
- `ui/src/api/client.ts` creates the openapi-fetch client with `baseUrl: globalThis.location.origin` and `credentials: "same-origin"`. The base URL is never configured, never from an environment variable, never another origin. No Authorization header is set (the loopback UI needs none; decision 0057 in the api contract). A test asserts the origin, the path and the absent header.
- `unwrap` turns every failure into an `ApiError` with a fixed message per kind (network, validation, unauthorized, forbidden, not_found, rate_limited, server, unknown). The server's `detail` is never copied into the message, so nothing a response carries (even a redacted message) reaches the page through an error.
- The schema file is not written by hand. In this task it could not be generated (decision 0324), so it is absent and `typecheck` fails on the missing import until the human fixes the toolchain and runs `mise run ui:gen`.
Alternative: `ui/src/api/schema.d.ts` as the card wrote it (not taken: outside the directory that eslint ignores and that 0300 and AGENTS.md treat as generated, so it would be linted and look hand-editable). `baseUrl: ""` (not taken: fails in tests and in any non-browser host; the origin is explicit and equal in a browser). A hand-written schema stub to make typecheck pass (rejected: a generated file is never hand-edited, and a stub would hide drift).
Reason: One generated directory with one rule; an explicit same-origin base makes the "no other origin" rule testable.
Consequences: Tauri (decision 0304) will serve the UI from another origin and will need its own base-URL decision then. The generated file is committed (so `gen-check` has something to compare) once it exists.
Where: `ui/src/api/client.ts`, `ui/src/api/errors.ts`, `ui/package.json` (`gen`), `mise.toml` (`ui:gen`), `scripts/ui.sh` (`gen-check`, patch).
Revisit when: The generator or the serving origin changes, or the mobile repo wants the same client package.
