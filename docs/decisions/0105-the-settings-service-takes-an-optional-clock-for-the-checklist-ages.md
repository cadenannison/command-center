# 0105. `SettingsService` takes an optional `Clock` so the checklist can say "3 min ago"

Status: accepted

Context: The setup checklist shows each source's last sync time as an age. The age needs "now". Services must not call `datetime.now()`; the web layer has no clock and may not import the system one (an adapter); `AgendaService`, which has a clock, is being edited by another session.
Decision: `SettingsService(..., clock=None)` and `checklist(items)`, which returns `SetupItem`s with `seconds_ago` computed from the clock (None without one or without a sync). The web layer only words the number (`format_age`). `app.py` passes its `SystemClock`. The parameter is optional so existing constructions (tests, other callers) keep working; without a clock the checklist shows state but no age.
Alternative: Compute the age in the browser (JavaScript, which the card avoids); add a `now()` to `Container` (touches every composition root and test rig); or read the clock from `AgendaService`.
Reason: A constructor parameter is the repo's pattern for time in services and the change is one line in `app.py`.
Where: `src/command_center/services/setup_checklist.py`, `SettingsService.checklist`; `web/checklist.py`; `app.py` (`build_container`).
Revisit when: The workers or desktop root build a `SettingsService` that shows the page: pass the clock there too.
