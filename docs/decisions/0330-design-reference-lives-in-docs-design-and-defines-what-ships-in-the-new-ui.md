# 0330. The design reference lives in docs/design and defines what ships in the new UI

Status: accepted

Context: The new UI (decisions 0300-0304) needs a visual and behavioural target. The project manager supplied a clickable prototype and a written spec (Nov 12, 2026).
Decision: `docs/design/` holds the reference: `spec.md`, `prototype.html` (fonts and logo in `assets/`, no base64), `tokens.json` (extracted from the prototype's `:root`) and a README. It is reference material, not shipped code. Order of authority: spec.md, then prototype.html, then tokens.json. What ships in the left rail: Today, Chat, History, Focus at the top; a Privacy toggle and Settings at the bottom. The prototype's "Design rules" page never ships. Everything else the spec describes (titlebar, grid, widget anatomy, states, motion, Chat, History, Settings) is the target for ui/ tasks, built one widget at a time with its /v1 endpoint first (0302).
Alternative: Copy the prototype into ui/ and evolve it (rejected: it is one hand-written file with inline script and style, which the strict CSP of 0301 forbids, and it has no typed client). Keep the design outside the repo (rejected: sessions could not read it and it would drift).
Reason: A fixed order of authority settles disagreements without asking: the prose spec states intent, the prototype shows it, the tokens are a machine copy of the prototype.
Consequences: Nothing under docs/design is imported by ui/ or served. ui tasks cite the spec section they implement. The prototype uses inline script and style; that is acceptable only because it is not shipped. Where it conflicts with an architecture rule (AGENTS.md), the rule wins and the conflict gets a decision record.
Where: `docs/design/README.md`, `spec.md`, `prototype.html`, `tokens.json`, `assets/`.
Revisit when: the UI reaches cutover, at which point the reference may be trimmed or archived, or the design changes (update spec.md first).
