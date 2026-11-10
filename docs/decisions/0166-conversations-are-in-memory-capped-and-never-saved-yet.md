# 0166. Conversations are in memory, capped at 20 turns, and not saved yet

Status: accepted

Context: The card keeps conversations in memory, capped at 20 turns, "not stored unless a save-chats setting is on (default off)". There is no storage layer or table for chats in the card, and a stored chat would hold the agenda text and the user's questions.
Decision: `ChatService` keeps at most 20 conversations (least recently used dropped) of at most 20 turns each (the oldest turns are dropped first, always as whole user/assistant pairs so a conversation never begins with a reply). A message is at most 2000 characters; a reply is trimmed to 8000. A conversation id is an opaque id from the `IdSource`; an unknown id is 404, not a new conversation, so a client cannot choose an id. The "save chats" setting is not built: nothing is written to disk, and a restart forgets every conversation. One lock per service makes the order of turns deterministic.
Alternative: Build the save-chats table now (storage, migration, retention and delete-on-forget with no consumer; a decision for the history UI session); unbounded memory (a loop of messages would grow it without limit).
Reason: Not storing is the safe default, and the setting has nothing to guard until a store exists.
Where: `src/command_center/services/chat.py`, `core/chat.py` (`cap_turns`); `tests/test_chat_service.py`, `tests/test_core_chat.py`.
Revisit when: Someone wants chats to survive a restart; add the table, the setting (default off) and a delete that clears both.
