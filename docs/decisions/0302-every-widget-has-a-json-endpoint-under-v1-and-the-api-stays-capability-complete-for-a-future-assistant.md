# 0302. Every widget has a JSON endpoint under /v1, and the API stays capability-complete for a future assistant

Status: accepted

Context: Today some pages are rendered by `web` from services directly and have no JSON twin, so a client other than the Jinja pages (the new UI, the phone app, a future assistant) cannot do what those pages do. A working-name assistant, Instinct (backlog), is planned to act for the user over the same API.
Decision: The new UI talks to the app only through /v1.
- Each widget (agenda, week and month views, sources and their state, settings, chat, summary, check-off, notes, local tasks, history, and the rest) has a JSON endpoint under /v1 that returns what the widget shows and accepts what it changes.
- Pages move into /v1 as they are ported: a UI task that needs data the API does not yet return first adds the endpoint (an api and services task), then the screen. An endpoint is additive; an existing path or schema is never renamed or removed (AGENTS.md; decision 0300 and `docs/standards.md`).
- Capability-complete: anything a person can do in the UI, a caller with the same credentials can do through an endpoint that is documented in `docs/generated/openapi.json`. The UI gets no private routes, no server-side state, and no behaviour that only exists in a template or in the browser. If a rule matters (redaction, opt-in summary, write-only settings), it lives in core or a service so every caller gets it.
- Instinct is not built or designed here. It is recorded so that endpoint design does not close it off: its actions will be the endpoints, with the same validation, rate limits and secret rules as the UI. Anything it can read is subject to the same redaction rule (AGENTS.md rule 6) as a summary provider.
Alternative: Let the UI call services through server-rendered islands or private routes (rejected: a second contract that the phone app and an assistant cannot use). Build the assistant's own tool API (rejected: two APIs for one set of capabilities would drift). Port every page first and expose the API afterwards (rejected: the API shape is what lets the UI be tested and the generated client be typed from the start).
Reason: One public contract is cheaper to secure and test than several, and it is what the mobile repo already depends on. Making the UI a client of it proves the API is complete.
Consequences: The first UI tasks include small api and services tasks. Each new endpoint is a /v1 addition with an openapi.json change, so the reviewer checks it for being additive. Voice or assistant features inherit every limit the API has.
Where: `docs/contracts/api.md`, `docs/generated/openapi.json` (the contract), `docs/backlog.md` (Instinct item).
Revisit when: The assistant is designed (it may need a scoped credential or an action log, which is a new record), or a widget cannot be expressed as an endpoint.
