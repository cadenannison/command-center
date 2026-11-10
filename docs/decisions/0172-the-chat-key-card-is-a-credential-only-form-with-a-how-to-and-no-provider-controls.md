# 0172. The chat key card is a credential-only form with a how-to and no provider controls

Status: accepted

Context: Decision 0170 made the `chat` integration always registered, so the settings page lists it; without a form it fell back to a bare "chat" card with a Sync button. The project manager asked for a card like Gemini's, with the provider and model controls left to the C2 card.
Decision: `web/sources.py` gets `SOURCE_FORMS["chat"]`: label "Chat provider key", one secret field `api_key` ("API key"), `credential_only=True` (no sync state, no Sync button, Connected once the key is set). `web/howto.py` gets a how-to: the key is for the chosen chat provider (OpenRouter, OpenAI); hosted providers need one, local providers (Ollama, LM Studio, llama.cpp) need none and the field stays empty; the key is kept in the keychain and only its last four characters are shown. Its closing note says saving a key does not turn chat on or choose a provider, and that chat with Gemini uses the Gemini key. No `note` caveat on the card: what chat sends is in `docs/sources.md` and `GET /v1/chat/context-preview`. The label does not say "chat" alone, so the how-to heading reads "How to connect Chat provider key".
Alternative: Name the card "Chat" (it would suggest the card chats or turns chat on); show the data-leaves caveat on the key card (chat can be on with no key, so the caveat belongs on the C2 card that turns it on).
Reason: The key must be enterable before chat is on, and a card that says what the key is for, and that local servers need none, stops a user pasting a Gemini key or hunting for a key Ollama does not use.
Where: `src/command_center/web/sources.py`, `web/howto.py`; `tests/test_web_chat_card.py`; `docs/contracts/web.md`.
Revisit when: The C2 card adds provider, address and model controls; fold this card into it or link the two.
