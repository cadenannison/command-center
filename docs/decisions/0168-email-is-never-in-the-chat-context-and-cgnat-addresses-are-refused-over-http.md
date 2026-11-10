# 0168. Email is never in the chat context, and CGNAT addresses are refused over http

Status: accepted

Context: The context is built from the agenda and optional history and notes. Items with kind `email` are in the agenda. Rule 6 says titles, due dates and trimmed subjects only, never bodies. Separately, `100.64.0.0/10` is carrier-grade NAT and Tailscale's range, which is neither the user's LAN nor a public address.
Decision: `build_context` leaves out every entry of kind `email` (a subject can name a person or an account; the AI summary may see trimmed subjects, chat gets none), so the context holds calendar and Canvas items only. `require_chat_base_url` treats `100.64.0.0/10` as not local: http to it is refused, and https to it fails `require_https_public`.
Alternative: Include trimmed subjects as the summary does (a chat can be asked anything, so the exposure is wider than a fixed summary prompt); allow CGNAT over http for tailnet-hosted models (the user can use `*.local`, a LAN name or https).
Reason: The smallest context that answers "what is due this week" and an address range the user cannot be sure is theirs.
Where: `core/chat.py` (`_EMAIL`), `core/urlcheck.py`; `tests/test_core_chat.py`, `tests/test_urlcheck_chat.py`.
Revisit when: Users ask to include email subjects in chat; make it a third opt-in with its own preview.
