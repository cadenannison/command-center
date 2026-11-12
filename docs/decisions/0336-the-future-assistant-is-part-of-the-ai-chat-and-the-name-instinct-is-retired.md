# 0336. The future assistant is part of the AI chat, and the name "Instinct" is retired

Status: accepted

Context: Decision 0302 and the backlog used a working name, Instinct, for a future assistant over the /v1 API. The design adds a Chat screen that is described as the AI assistant.
Decision: There is one assistant: the AI Chat. It reads items, suggests actions, and acts only through /v1 with the same validation and secret rules as the UI. It never sends email or changes a source (spec). The name Instinct is retired; the backlog item is renamed "assistant". Decision 0302 stays in force for everything about the API; only its Instinct wording is superseded, and its Status line says so.
Alternative: A separate assistant product beside Chat (rejected: two surfaces for one capability). Keep the name (rejected: it names something that no longer exists apart from Chat).
Reason: One name and one place for the assistant keeps the contract and the privacy copy (0333) consistent.
Consequences: Chat inherits the open questions from the backlog item: scoped credential, logged and reversible actions, what it may read (redaction applies), opt-in provider.
Where: `docs/backlog.md` (the assistant item), `docs/decisions/0302-*.md` (Status line only).
Revisit when: the assistant is designed in its own record.
