# 0358. The dashboard routes answer 404 until the container has a dashboard service

Status: accepted

Context: Items, chat and geocode are optional container fields so a test or process without the storage still builds an app.
Decision: `Container.dashboards` is `DashboardService | None`, last field, default None; the routes answer 404 `Dashboards are not enabled` while it is None. `command_center.app` builds it over the same `database_url` as the other stores. The service is a thin pass-through (ids from `IdSource`, time from `Clock`); all rules are in core and the stores.
Alternative: Always build a service with an in-memory store when none is given (rejected: silent data loss).
Reason: Matches the items pattern (0120) and keeps every existing test rig unchanged.
Consequences: The existing policy test rig has no service, so its read rows get a 404 there; `tests/test_dashboards_remote.py` proves the phone reads and is refused writes with a service wired.
Where: `services/container.py`, `services/dashboards.py`, `app.py`.
Revisit when: a second composition root (workers, desktop) needs the same stores.
