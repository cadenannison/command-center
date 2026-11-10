# 0104. After a failed submit the browser keeps the secrets the user typed; the server never sends them back

Status: accepted; not tested in a real browser (see Revisit)

Context: A failed connect used to re-render the card with empty inputs, so the user retyped everything. Task A1 wants non-secret fields to keep what was typed, but secrets must never be echoed in any response. "Save anyway (unverified)" also needs the typed secrets: it submits the form again.
Decision: The server puts the typed non-secret values into the new card and leaves secret inputs empty. When the response is a failure (`CardView.keep_typed`) the secret inputs carry `hx-preserve="true"`, so htmx keeps the existing input element, with its typed text, across the swap. "Save anyway" uses `hx-include="#form-<source>"` to resubmit the form. A success, and a fresh page, set no `hx-preserve`, so a stored secret is not left sitting in a field.
Alternative: Do not swap the card on failure (`HX-Reswap`/`HX-Retarget` onto the message line), which also leaves the form alone but makes the response a fragment without the typed plain values; or echo the secret into the password input (forbidden).
Reason: It satisfies "never echoed" by construction (the tests search every response for the typed secret) and keeps the response a whole card.
Where: `web/templates/_card.html`, `CardView.keep_typed` in `web/cards.py`. Tests assert the attribute and the absence of the value; the behaviour of `hx-preserve` itself is htmx's and was not exercised in a browser here (no browser is available to this session).
Revisit when: Someone clicks through a failed Connect and "Save anyway" in a browser. If a secret input is cleared, fall back to the retarget approach.
