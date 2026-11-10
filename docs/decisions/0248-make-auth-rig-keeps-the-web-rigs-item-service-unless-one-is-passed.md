# 0248. make_auth_rig keeps the web rig's item service unless one is passed

Status: accepted. Refines 0213.

Context: `make_auth_rig(items=None)` defaulted `items` to `None` and always wrote it into the container, so a caller that left it out silently removed whatever item service `make_rig` had built, and a future change to `make_rig` that wires one would be undone without anyone seeing it.
Decision: The default is a sentinel (`auth_rig.KEEP`). Only an explicit `items=` replaces the container's item service, and `items=None` removes it on purpose. Today `make_rig` builds a container with no item service, so a caller that left the argument out sees `None` before and after; the callers were checked: `test_auth`, `test_web_pair`, `test_pair_api`, `test_json_only_writes`, `test_cross_site_writes`, `test_geocode_api`, `test_chat_remote_policy`, `test_auth_websocket`, `test_settings_values_remote` call it with no `items`, and `test_remote_policy` passes a real service. All 224 tests that use it pass and none asserts "no item service" without having asked for it. `tests/test_auth_rig.py` holds the three cases.
Alternative: Make the default `make_rig`'s service explicitly (a second parameter on `make_rig`); leave `None` (the trap above).
Reason: A helper's default should mean "what the base rig has", not "nothing".
Where: `tests/auth_rig.py`; `tests/test_auth_rig.py`.
Revisit when: `make_rig` builds an item service itself; the tests that now add one by `replace` (`test_web_items_remote`, `test_items_remote_policy`) can then drop it.
