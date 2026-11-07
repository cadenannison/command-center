# 0027. SQLAlchemy errors do not carry bound parameters

Status: accepted

Context: When a statement fails, SQLAlchemy puts `[parameters: ...]` into the exception text. For `upsert` those are the event's title, link and `raw` fields. Since the sync runs as a background task (0025, 0026), a failing `upsert` is logged by the server with its traceback after the response has gone, so event content reached the logs. `POST /v1/sync` had the same exposure. Rule 5 forbids logging PII.
Decision: `create_event_store` creates the engine with `hide_parameters=True`. The error still names the statement and the database's reason; only the bound values are replaced.
Alternative: Catch and re-raise a sanitised error in `SyncService`, or log a fixed message and not re-raise. Rejected: it covers one caller only, and any other caller of the store (agenda reads, workers later) would keep the leak. The engine setting fixes it at the source.
Reason: One argument, no behaviour change for working queries, and it covers every statement, including `query` and the Postgres engine built through the same factory.
Where: `src/command_center/storage/sqlite.py` (`create_event_store`); `docs/contracts/storage.md`; test `tests/test_sqlite_error_details.py`.
Revisit when: Debugging a failed write needs the values; then enable them only for a local debug run, never by default.
