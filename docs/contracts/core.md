# Contract: core

Pure domain layer. Imports nothing in the app and no infrastructure library (see docs/MAP.md).

## Behaviour
- `ports.py` defines `Clock` (`now() -> datetime`, timezone-aware), `Rng` (`random() -> float` in [0,1)) and `IdSource` (`new_id() -> str`) as Protocols. Everything time-, random- or id-dependent takes one as a parameter.
- Reason: determinism. Any core function is reproducible from its inputs, so tests need no patching.

## Planned (not built yet)
- Schema: events, tasks/assignments, messages, weather, source status.
- Urgency scoring (deterministic, tunables passed in as data).
- Redaction for summaries: strips addresses and numbers, trims subjects, never carries bodies.
- Window math: day/week/month ranges in the user's timezone, DST-safe.
