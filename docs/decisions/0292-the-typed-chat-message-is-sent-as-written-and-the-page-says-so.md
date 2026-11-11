# 0292. The typed chat message is sent as written and the page says so

Status: accepted

Context: Redaction (AGENTS.md rule 6) runs on the context the app builds: titles, due dates and trimmed subjects. The message the user types in the chat box is not part of that context and is not redacted. It was never recorded as a choice, so a reader could take it for a gap. Review of the key-shape work raised it.
Decision: The user's own typed message is deliberately not redacted. `ChatService.reply` checks only its length (1 to 2000 characters) and passes it to the provider as written. The chat panel says so in one plain line under the message box: "What you type here is sent to the provider exactly as written." (`web/templates/_chat_panel.html`, `id="chat-message-note"`). The context is still redacted before any provider sees it, and an email body is never included (decisions 0163, 0164).
Alternative: Redact the typed message too (rejected: the user chose the words and the provider is the one they turned on; redaction would silently change a question such as "is the 2pm call on 555-0100?" and the user could not see what was sent). Say nothing (rejected: the user would assume the same masking as the context).
Reason: Redaction protects data the app picked up on the user's behalf. Text the user types is something they decided to send, so the right control is to tell them, not to rewrite it.
Consequences: A secret pasted into the chat box reaches the provider. The line says that; chat is off by default and the provider is the user's choice. The line shows while chat is off too, since the box is on the page.
Where: `web/templates/_chat_panel.html`, `docs/contracts/web.md` (Chat page paragraph); `tests/test_web_chat.py` (`test_the_page_says_the_typed_message_is_sent_exactly_as_written`).
Revisit when: A provider is added that the user does not choose, or a way to attach files or paste from the dashboard to the box is added.
