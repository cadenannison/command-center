# Security policy

## Reporting a vulnerability
Use GitHub's **private vulnerability reporting**: on the repository page choose *Security* →
*Report a vulnerability*. Please do not open a public issue or post details publicly. You should get
an acknowledgement within a week.

## Scope
Command Center is a personal, local-first app: the server binds to 127.0.0.1 and secrets are stored only
on this computer (the OS keychain, or a protected file under Docker). Of particular interest: anything that exposes data beyond loopback, leaks a secret or token,
sends data to a summary provider that the privacy rules forbid (docs/decisions/0004-summaries.md), or
weakens phone pairing (docs/decisions/0002-local-first-api.md).

## Supported versions
Only the latest revision on `main`.
