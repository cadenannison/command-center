# 0333. AI features are off by default and every privacy line must match real behavior

Status: accepted

Context: The Settings card for AI and the privacy copy tell people what leaves their machine. A wrong line is worse than none. AGENTS.md rule 6 already makes summaries opt-in.
Decision: The AI summary, draft replies and AI-suggested estimates are each off by default and each has its own toggle. Every privacy line in the UI (Settings, Chat, the Privacy toggle, setup) must describe what the code does, and each is covered by a wording test that fails when the text or the behavior it describes changes. The Ollama copy must not claim the data stays on this machine: the address can point at another host on a LAN, so the copy says data goes to the address you entered and names the local machine only when that address is loopback. A line about a cloud provider states what it receives (titles, due dates and trimmed subjects, per the redaction in core).
Alternative: Static marketing-style copy (rejected: it drifts from behavior). Say "stays on this Mac" for any Ollama setting (rejected: false for a LAN address).
Reason: Honest copy is part of the privacy rule; a test turns a docs promise into a gate.
Consequences: Wording tests are new tests in the task that adds each line; changing a privacy line means changing its test with a task card saying `tests: modify`.
Where: not built yet; `ui/` copy and its tests; the existing Jinja wording is covered by earlier decisions (0190-0192).
Revisit when: a provider type is added, or a setting changes what is sent.
