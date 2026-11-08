# 0038. AgendaService exposes `today()` and `tz` for the web views

Status: accepted

Context: The web pages default to "today" and must place events on the user's local days (week columns, month cells, "06:00" labels). Only `AgendaService` holds the `Clock` and the configured timezone; `Container` exposes neither, the web layer may not import adapters (`SystemClock`) and `datetime.now`/`date.today` are banned outside composition roots. The task card fixes `create_router(container)` as the signature and says layer: web.
Decision: Add `AgendaService.today() -> date` (clock now, in `tz`) and a read-only `AgendaService.tz` property. No other service changes.
Alternative: (a) `create_router(container, *, clock, tz)`: breaks the signature the card fixes, and the mounting task would have to rebuild the clock and tz it already gave `AgendaService`. (b) Put `clock` and `tz` on `Container`: a wider change to a shared dataclass every caller builds. (c) The web layer reads `agenda._tz`: reaches into a private.
Reason: The service already owns both facts; two small accessors keep one source of truth, keep the card's signature, and are testable with `FakeClock`.
Where: `src/command_center/services/agenda.py`; `tests/test_agenda_today.py`; `docs/contracts/services.md`.
Revisit when: Several services need the clock and tz (then a shared `Calendar` helper on `Container` is cleaner), or per-user timezones arrive.
