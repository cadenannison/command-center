# web

Contract: `docs/contracts/web.md` (`## Routes` is the quick map). Rules that load here:
`.claude/rules/layers.md`, `style.md`, `tests.md`.

- Jinja2 + HTMX views. Imports services, core and `pairing` (QR only); never adapters or storage.
- Handlers parse and validate, call one service method, render. Every non-GET request must carry the
  per-process CSRF token in `X-CSRF-Token` (`csrf.py`). `loopback.py` has two parts: `require_loopback`,
  a per-route dependency that 404s a request not from the Mac's own browser, and `is_loopback`, the flag
  every template gets so a paired phone sees Today, Week, Month and History read-only (decision 0210).
  A new route decides which of the two it needs. The server binds 127.0.0.1 (AGENTS.md rule 5).
- Inline htmx scripts are intentional for now; moving them to a static file is a backlog item that only
  matters if a CSP is added (decision 0212).
- The shared test rig is `tests/web_rig.py`. A new page gets a route test through it, not a hand-built app.
- Nothing secret is rendered or put in a URL. The AI summary and chat are opt-in and off by default
  (AGENTS.md rule 6).
