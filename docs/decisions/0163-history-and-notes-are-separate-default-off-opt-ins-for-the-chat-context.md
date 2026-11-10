# 0163. History and notes are separate default-off opt-ins for the chat context

Status: accepted. Supersedes the "never sent to the AI" part of 0125 for chat only.

Context: Decision 0125 keeps notes out of every AI prompt. The chat card asks for history and notes as optional context, each its own setting, default off.
Decision: `chat.include_history` adds the last 7 days of the ledger (done, done at source, gone) and `chat.include_notes` adds the note of each agenda item and history entry that has one, trimmed to 200 characters; both default off and each works without the other. Every note and title is collapsed, redacted, neutralised and trimmed, in that order, and the whole context is capped at 6000 characters (`(more items omitted)` marks a cut). The agenda block lists open items only: an item the user checked off or the source finished (status `done`) appears only in the history block, so it never leaks without that opt-in. The summary feature still never sees a note: 0125 stands for it. Email is not part of the chat context at all (decision 0168).
Alternative: One "send my history" switch (a user who wants history but not their private notes would have no choice); notes always (breaks 0125 without consent).
Reason: A note is private by decision 0125; sending one is an act the user must opt into by itself, and the preview shows the text that would go.
Where: `core/chat.py` (`build_context`), `services/chat.py`, `services/chat_settings.py`; `tests/test_core_chat.py`, `tests/test_chat_service.py`.
Revisit when: A reason appears to send a note to the summary too; that is a new decision against 0125.
