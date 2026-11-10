# adapters

Contract: `docs/contracts/adapters.md` (large: read `## Rules for every source adapter`, then only the
section for the adapter you edit). Rules that load here: `.claude/rules/style.md`, `tests.md`.

- Imports `core` only, and never `storage`. Implements a Protocol from `core/ports.py`.
- Each vendor SDK is imported in exactly one file (`docs/MAP.md`, "Vendor SDK, one adapter file each";
  enforced by import-linter). Do not import `caldav`, `googleapiclient`, `google`, `keyring`, `redis` or
  `rumps` anywhere else.
- Outbound HTTP goes through the shared guards: `net_guard.py` (SSRF check at DNS time) and `http_cap.py`
  (response size cap). Chat and city-search calls ignore proxy settings from the environment
  (decisions 0225, 0246). Check those records before adding an outbound path.
- Nothing secret is logged or put in a URL (AGENTS.md rule 5). Test credentials start with `fake-`.
- Tests mock HTTP with respx at the httpx boundary. Never hit a real service.
- A new adapter file needs a line in `docs/MAP.md` and the contract.
