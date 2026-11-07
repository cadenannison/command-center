# 0001. Two run modes

Status: accepted

Context: A personal dashboard should install and run with no infrastructure, but the author also wants to learn distributed systems.
Decision: Default is single process, SQLite and an in-process queue. Opt-in distributed mode is Docker Compose with Redis Streams, Postgres and one worker per source.
Consequences: Queue and storage sit behind ports so both modes share all service code. Redis and psycopg are optional extras (`distributed`); redis is imported only in `adapters/queue_redis.py`. CI exercises the default mode; distributed tests are env-guarded.
