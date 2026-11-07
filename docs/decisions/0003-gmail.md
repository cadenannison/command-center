# 0003. Gmail access

Status: accepted

Context: Gmail's API needs an OAuth client; shipping one in the repo would expose it and require Google verification.
Decision: Scope is `gmail.readonly`. The user brings their own OAuth client; no client id or secret is ever in the repo. While the client is unverified, Google expires refresh tokens after 7 days.
Consequences: The UI shows a Reconnect state when a token is rejected. Setup docs explain creating a Google Cloud client. Only `adapters/gmail.py` imports the Google client libraries.
