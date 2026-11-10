# 0213. `make_auth_rig` takes an `items` argument, which edits `tests/auth_rig.py` beyond the card's file list

Status: accepted

Context: Task X item 4 asks that `make_auth_rig` take an `items=` argument, so `tests/test_remote_policy.py` stops building a rig and then discarding its app and clients to rebuild them with an item service. `make_auth_rig` lives in `tests/auth_rig.py`, which the card's list of editable tests (`test_remote_policy.py`, `route_support.py`) did not name.
Decision: Add the keyword `items: ItemService | None = None` to `make_auth_rig` and put it in the container it builds. Every existing caller passes nothing and gets what it got. The fixture in `test_remote_policy.py` is now one line. The edit to `tests/auth_rig.py` is only that argument.
Alternative: Leave the fixture's rebuild as is and skip item 4's second half; or stop and ask.
Reason: The item names the function and the change is not possible anywhere else.
Where: `tests/auth_rig.py`, `tests/test_remote_policy.py`.
Revisit when: Never needed; a project manager who meant a narrower scope can revert the one argument.
