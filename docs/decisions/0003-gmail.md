# 0003. Gmail access

Status: accepted

Context: Gmail's API needs an OAuth client; shipping one in the repo would expose it and require Google verification.
Decision: Scope is `gmail.readonly`. The user brings their own OAuth client; no client id or secret is ever in the repo. While the client is unverified, Google expires refresh tokens after 7 days.
Consequences: The UI shows a Reconnect state when a token is rejected. Setup docs explain creating a Google Cloud client. Only `adapters/gmail.py` imports the Google client libraries.
Sources (checked 2026-11-07): https://www.unipile.com/google-oauth-refresh-token/ supports the 7-day claim. It says Google expires all refresh tokens issued by unverified apps after 7 days, specifically when the OAuth consent screen is in "Testing" status and the app is not verified, and that internal Workspace apps are exempt. It is a third-party article that points to Google's own documentation for the rule and does not quote it, so it is a secondary source.
