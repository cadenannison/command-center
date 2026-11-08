# 0050. The Redis queue lives in adapters/queue_redis.py

Status: accepted

Context: The task card for 3a names the file `adapters/redis_streams.py`. Decision 0001, `docs/contracts/adapters.md`, `docs/MAP.md` and the import-linter contract in `pyproject.toml` ("redis only in adapters/queue_redis.py") all name `adapters/queue_redis.py`. The adapters contract says an adapter task must not edit `pyproject.toml` to add a vendor SDK file.
Decision: The Redis queue is `src/command_center/adapters/queue_redis.py`, the file the import contract already allows. The in-process queue is `adapters/inprocess_queue.py` as the card says.
Alternative: Follow the card, create `redis_streams.py` and change the import-linter contract.
Reason: The card's intent is "redis is imported in exactly one adapter file", which `queue_redis.py` satisfies; renaming would widen the task into `pyproject.toml`, `MAP.md` and decision 0001.
Where: `src/command_center/adapters/queue_redis.py`, `pyproject.toml` (unchanged).
Revisit when: the owner prefers the name `redis_streams.py`; then one change updates the file, the contract and MAP together.
