# 0014. Invented test secrets start with "fake-" and gitleaks allowlists that prefix

Status: accepted

Context: Every adapter test needs a token, app password or feed URL to pass through the code. gitleaks' default `generic-api-key` rule flags invented values that merely look like keys, which would fail `mise run secrets` on harmless fixtures.
Decision: Invented test credentials start with `fake-`, and `.gitleaks.toml` allowlists secrets matching `^fake-`. The pattern is matched against the secret itself (`regexTarget = "secret"`), not the whole line, so a real key cannot hide behind a `fake-` elsewhere on its line. The default gitleaks rules stay on for everything else.
Alternative: Allowlist the `tests/` path, or mark each fixture with an inline `gitleaks:allow`. A path allowlist would also hide a real key pasted into a test file, and inline markers have to be remembered on every new fixture.
Reason: One prefix rule is cheap for every test author and keeps real-looking secrets in tests visible to the scanner.
Where: `.gitleaks.toml`; the rule for agents is in AGENTS.md (Working style).
Revisit when: A real secret is ever found that starts with `fake-` (or was hidden behind this allowlist). Then narrow the pattern or drop the allowlist and switch to a different mechanism.
