# 0167. The summary providers are not rebuilt on the chat port, and Gemini chat lives in the summary adapter file

Status: accepted

Context: The card says the summary providers are rebuilt on the same ports with behaviour unchanged. They have a different port (`SummaryProvider`: one prompt in, one summary out), different defaults and a different failure translation, and rule 4 allows google-genai in exactly one file, `adapters/summary_gemini.py`.
Decision: `ChatProvider` is a new port beside `SummaryProvider`; the summary providers and their tests are untouched. `GeminiChatProvider` is added to `summary_gemini.py` (the one file that may import the SDK) and reuses its key reading and error translation (`_read_key`, `_translate_chat`); Ollama and OpenAI-compatible are new files using httpx only (`chat_ollama.py`, `chat_openai.py`, `chat_http.py`). The summary classes are not made thin wrappers over chat.
Alternative: Rewrite the summary providers over `ChatProvider` (risk to behaviour that 3000 tests pin, for no feature); a new `chat_gemini.py` (a second file importing the SDK breaks rule 4 and the import-linter contract, which a pyproject edit would be needed to change).
Reason: The statement "behaviour unchanged" is cheapest to keep true by not touching it.
Where: `src/command_center/adapters/summary_gemini.py`, `adapters/chat_*.py`, `core/ports.py`.
Revisit when: A third consumer of a one-shot completion appears; fold the two ports then.
