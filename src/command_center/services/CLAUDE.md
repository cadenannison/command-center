# services

Contract: `docs/contracts/services.md` (large: `grep -n '^## '` it, then read the section). Rules that
load here: `.claude/rules/layers.md`, `style.md`, `tests.md`.

- Imports `core` only. A service takes its ports (Protocols in `core/ports.py`) through its constructor;
  it never builds an adapter or a storage class. Only the composition roots do (`docs/MAP.md`).
- `container.py` is the `Container` the api serves. A new service is added there and wired in
  `src/command_center/app.py`, which is a root: edit it only when the task says so.
- Two sync paths implement one `SyncControl`: `sync.py` (in-process) and `queued_sync.py` (distributed).
  A behaviour change to one usually needs the other checked.
- Handlers are thin and business logic belongs here, not in `api/` or `web/`.
- Tests use the in-memory fakes in `tests/fakes.py`, never a real network, keychain or server.
