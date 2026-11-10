# 0164. The context rides in the system prompt between markers, as untrusted data

Status: accepted

Context: A title or note is text from a calendar feed or a school system; anyone who can put an event on the user's calendar can write it. A model may obey instructions found in it.
Decision: `core/chat.py` `build_system(context)` makes the system prompt: the trusted instructions (read-only, no tools, cannot change anything, the data is untrusted and never instructions), then the context between `<<<CONTEXT` and `CONTEXT>>>`, then a closing line saying everything between the markers was data. Every `<` and `>` in untrusted text becomes `‹` or `›`, so no text can forge either marker (both need `<` or `>`). The user's turns are separate messages, never part of the system text. The model has no tools and no function-calling parameter is sent, so an injected instruction has nothing to call. A test checks the structure of the prompt: the injection string sits inside the markers, appears once, and no marker appears inside the context.
Alternative: Put the context in the first user turn (the user's words and the feed's words would share a channel); XML-style tags (an event title could close them); strip suspicious phrases (an arms race the attacker wins).
Reason: Structure, not filtering: the instructions are fixed and trusted, the data is fenced and cannot close its own fence.
Where: `src/command_center/core/chat.py`; `tests/test_core_chat.py`, `tests/test_chat_service.py::test_an_injection_string_stays_inside_the_context_block`.
Revisit when: A provider offers a separate untrusted-content channel; use it in the adapter.
