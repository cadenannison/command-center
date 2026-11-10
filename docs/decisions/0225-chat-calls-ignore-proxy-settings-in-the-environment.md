# 0225. Chat calls ignore proxy settings in the environment

Status: accepted

Context: httpx trusts the environment by default: `HTTP_PROXY`, `ALL_PROXY` and (on macOS) the System Settings proxy route a request through a proxy. For an http address a proxy receives the whole request in clear text, `Authorization` header and agenda included, even for `http://localhost:...`, which `may_send_key` allows (0220). A proxy also chooses where to connect, so it skips every address check in `checked_base_url` (0160, 0221). Found by the review of Task Y; the second effect is older than this task.
Decision: `chat_http.post_json` builds its client with `trust_env=False`, so neither provider uses a proxy from the environment or the system. As a side effect httpx also stops reading `SSL_CERT_FILE` and `SSL_CERT_DIR` for these calls and verifies with its bundled CA list. A test sets proxy variables and asserts the client was built with `trust_env=False`.
Alternative: Keep proxy support for https only (a CONNECT tunnel hides the key, but the proxy still bypasses the address checks, and httpx has no simple switch for it); keep `trust_env` and refuse to send a key when a proxy is configured (a proxy setting would silently turn chat off); leave it (the key goes to the proxy in clear text).
Reason: Fail closed: a personal dashboard talking to Ollama or a LAN server has no use for a proxy, and the checks mean nothing if a proxy can pick the destination.
Where: `src/command_center/adapters/chat_http.py` (`post_json`); `tests/test_chat_provider_hardening.py`; `docs/contracts/adapters.md`.
Revisit when: A user behind a mandatory proxy or a private CA needs a public https provider: add an explicit chat setting for a proxy URL or a CA bundle, validated like the base URL, instead of trusting the environment.
