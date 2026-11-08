# 0043. `adapters/gmail.py` may import the `google` namespace; arch no longer proves it avoids google-genai

Status: accepted

Context: The import-linter contract "google-genai only in adapters/summary_gemini.py" forbids the whole top-level package `google`, because import-linter reduces an external package to its top-level name. The Gmail adapter must import `google.oauth2.credentials.Credentials` (rebuild credentials from the stored client file and refresh token) and `google.auth.exceptions.RefreshError` / `TransportError` (turn a rejected token into `AuthExpired`). google-auth shares the `google` namespace with google-genai. A throwaway `gmail.py` importing `google.oauth2.credentials` made `mise run arch` report that contract broken (`command_center.adapters.gmail -> google`).
Decision: Add `"command_center.adapters.gmail -> google"` to that contract's `ignore_imports` in `pyproject.toml` (added by the project manager; adapter tasks may not edit `pyproject.toml`). The google-genai SDK is imported only by `summary_gemini.py`, and that is now enforced by review: `gmail.py` and `gmail_mail.py` must not import `google.genai`.
Alternative: Catch `RefreshError` by class name and avoid `google.oauth2`, or load it with `importlib`. Both evade the contract instead of respecting it, and the first cannot rebuild credentials at all. Narrowing the forbidden module to `google.genai` is not possible while import-linter squashes external packages to their root (not tried).
Reason: google-auth is not a separate top-level package, so no import-linter rule can tell it from google-genai.
Where: `pyproject.toml` (`[[tool.importlinter.contracts]]` "google-genai only in adapters/summary_gemini.py"); `src/command_center/adapters/gmail.py`; `docs/MAP.md` (vendor-SDK table).
Revisit when: import-linter can forbid a submodule of an external package (then forbid `google.genai` and drop the ignore), or a third adapter needs `google.*`.
