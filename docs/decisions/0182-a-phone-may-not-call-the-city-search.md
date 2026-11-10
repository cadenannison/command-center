# 0182. A paired phone may not call the city search, though it is a read

Status: accepted

Context: Task W1 says the search is loopback only. `api/policy.py` lets a paired phone make any GET, and `tests/test_remote_policy.py` fails until every route is classified in its table. The route spends the user's Open-Meteo quota and takes free text, and only the Mac's own web form needs it.
Decision: `api/policy.py` gets `REMOTE_DENIED_READS`, a set of paths a phone may not call by any safe method; `remote_may_call` checks it first. It holds `/v1/geocode`. A phone with a valid token gets 403 `A paired phone may not do this` and the service is not reached; a tailnet caller with no token is 401, as for every route. `tests/test_remote_policy.py` gets one row, `("GET", "/v1/geocode"): DENIED`, added under the project manager's `allow-test-edits` permission for that row only. No other existing test changed.
Alternative: A check inside the handler on the request's Host (a second place that decides who is remote, which `api/auth.py` already does from the Host and proxy headers); put the route outside `/v1` (it would not be in `openapi.json`, but the card names `/v1/geocode`).
Reason: The policy file is where "what a phone may do" lives and where the table test looks, so a new read that a phone must not make is refused in the same place and fails a test if someone removes it.
Where: `src/command_center/api/policy.py`; `tests/test_remote_policy.py` (the new row); `tests/test_geocode_api.py::test_a_paired_phone_is_refused_and_nothing_is_searched`.
Revisit when: The phone app needs to search for a city itself; the path then leaves the set and the table row becomes `READ`.
