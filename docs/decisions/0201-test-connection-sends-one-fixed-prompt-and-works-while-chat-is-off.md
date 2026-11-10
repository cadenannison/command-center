# 0201. "Test connection" sends one fixed prompt and works while chat is off

Status: accepted

Context: The AI card needs a button that shows the provider settings work. Decision 0169 says nothing leaves while chat is off; its reason is that the agenda is user data.
Decision: `ChatService.test_connection()` sends two fixed lines ("This is a connection test. Reply with the single word OK." and "Reply with OK.") to the provider built from the stored settings. No agenda, history, note or typed text is in it, and no conversation is kept. It works while chat is off, because a user checks a provider before turning chat on; pressing the button is the opt-in. It runs under the same lock and counts against the 10 per minute limit. It tests the saved settings, not the unsaved form, so it never validates or sends to an address nobody saved; the card says "save first". The route answers 200 with a line: "OK: the provider answered the test." (the provider's reply is not shown) or the service's fixed, redacted error text.
Alternative: Test the typed form values (a second path that builds a provider from unsaved input); refuse while chat is off (the user could not check a setup before opting in); show the provider's reply (provider text on the page).
Reason: The fixed prompt carries nothing of the user's, so rule 6 is not weakened, and the user can finish setup before opting in.
Where: `src/command_center/services/chat.py` (`test_connection`), `web/ai_settings.py` (`POST /ai/test`); `tests/test_chat_test_connection.py`, `tests/test_web_ai_settings.py`.
Revisit when: The test should check an unsaved address (then validate it with `require_chat_base_url` first), or a provider charges enough that the test needs its own limit.
