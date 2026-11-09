# 0072. `CC_BIND_ALL=1` is the only way to listen beyond loopback

Status: accepted; its claim that the published port stays loopback-only is qualified by 0090: with `CC_BIND_ALL` set any container on the compose network passes the loopback Host check, so the compose network is a trusted boundary

Context: Decision 0013 made `Settings.host` `Literal["127.0.0.1"]` and said the distributed task must add an explicit opt-in rather than loosen the default. Inside a container the server must listen on `0.0.0.0` or the published port is unreachable.
Decision: `Settings.host` stays loopback-only. A separate boolean `Settings.bind_all` (`CC_BIND_ALL`, default false) makes the read-only property `listen_host` return `0.0.0.0`; `app.main()` passes `listen_host` to uvicorn. `docker-compose.yml` sets `CC_BIND_ALL=1` on the `api` service only; no other service listens on HTTP. Every published port in compose is `127.0.0.1:<port>:<port>`, so the host's loopback is still the only reachable address (and Tailscale Serve, 0002, still fronts it).
Alternative: (a) Widen `host` to accept `0.0.0.0`: any stray `CC_HOST` would then expose the API. (b) Run the container with host networking: not available on Docker Desktop for Mac, and it drops the port mapping that enforces loopback. (c) A command-line flag on uvicorn in the Dockerfile: bypasses `Settings`, so the opt-in would not be one tested place.
Reason: the opt-in is one named variable that is false unless set, appears in exactly one compose service, and is covered by a test, while the loopback default and the `host` validation are untouched.
Where: `config.py` (`bind_all`, `listen_host`), `app.py` (`main`), `docker-compose.yml`; tests `test_config_distributed.py`.
Revisit when: the api is put behind a reverse proxy in its own network (then it could listen on that interface only); a non-Docker deployment needs a non-loopback bind.
