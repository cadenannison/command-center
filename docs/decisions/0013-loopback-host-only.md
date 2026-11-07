# 0013. Settings.host is loopback only

Status: accepted

Context: AGENTS.md rule 5 says the server binds 127.0.0.1, and remote access is Tailscale Serve (0002). `Settings.host` could have been a free string that anyone widens with `CC_HOST=0.0.0.0`.
Decision: `Settings.host` is `Literal["127.0.0.1"]`. Any other value fails validation at startup.
Reason: Binding beyond loopback exposes the API and every stored event to the network, so it should be a deliberate code change, not an environment variable that is easy to set by accident.
Consequences: Distributed mode (the Docker task) will need to listen on a non-loopback address inside a container. That task revisits this decision and must add an explicit opt-in, not loosen the default. Until then there is no setting that widens the bind.
