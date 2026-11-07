---
paths:
  - "src/command_center/services/**/*.py"
  - "src/command_center/api/**/*.py"
  - "src/command_center/web/**/*.py"
  - "src/command_center/workers/**/*.py"
  - "src/command_center/pairing/**/*.py"
  - "src/command_center/desktop/**/*.py"
---
- Services receive their ports through the constructor; no SQL, socket, keyring or filesystem code inside
  a service, and no `datetime.now()` (take a Clock).
- Route handlers and HTMX views are thin: parse and validate, call one service method, respond.
- Log structured JSON through the logging port; never log secrets, tokens, PII or email content.
- The settings API is write-only: return status (set + last4), never the value.
- Pairing tokens are short-lived and single-purpose; the server binds 127.0.0.1 only.
- Views and menu-bar code import no adapter; every user action goes through a service method.
