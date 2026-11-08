# 0036. Summary providers live in `summary_gemini.py` and `summary_ollama.py`; Gemini 3.5 Flash-Lite by default

Status: accepted

Context: The task card names `adapters/gemini.py` and `adapters/ollama.py`. The adapters contract, `docs/MAP.md` and the import-linter rule "google-genai only in adapters/summary_gemini.py" name `summary_gemini.py` and `summary_ollama.py`. AGENTS.md rule 4 says the contract names the file in pyproject.toml, and adapters rule 7 forbids adding a file name from an adapter task. The card also says the Gemini default is "a current Flash-Lite model; verify the name".
Decision: Use the contract's file names. The default Gemini model is `gemini-3.5-flash-lite`, checked on 2026-11-07 against https://aistudio.google.com/docs/models/gemini-3.5-flash-lite (stable, last updated July 2026, structured outputs supported). `CC_SUMMARY_MODEL` overrides it; unset means each adapter's own default (Ollama: `llama3.2`, which the user must have pulled). The key is read from the secret store (source `gemini`, key `api_key`) on every call, so a changed key applies without a restart. Ollama is reached at the fixed `http://localhost:11434` in JSON mode; the URL is not a setting, so the URL guard of adapters rule 5 does not apply.
Alternative: Use the card's names: `mise run arch` would fail on the SDK import (rule 4) and the contract would disagree with the code.
Reason: The contract and the enforcing lint agree with each other and are older than the card.
Where: `src/command_center/adapters/summary_gemini.py`, `summary_ollama.py`; `src/command_center/config.py`; `docs/contracts/adapters.md`.
Revisit when: Google retires the model name, or a remote Ollama is wanted (then the URL becomes a setting behind `require_https_public`).
