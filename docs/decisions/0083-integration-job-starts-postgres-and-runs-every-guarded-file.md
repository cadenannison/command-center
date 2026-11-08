# 0083. The non-required `integration` job starts Postgres and runs every env-guarded file

Status: accepted

Context: Task 4a. The `integration` job started a Redis service and ran only `tests/test_job_queue_contract.py`. Decisions 0071, 0074 and 0075 added cases that need `CC_TEST_REDIS_URL` (chaos, report stream, normalizer) and `CC_TEST_POSTGRES_URL` (report sink, generation column, normalizer, sink chaos). They had never run against a real Redis or Postgres.
Decision: the job now also starts `postgres:17-alpine` (the version in `docker-compose.yml`) with user `cc`, password `fake-ci-postgres-password`, database `postgres`, a `pg_isready` health check, and sets `CC_TEST_POSTGRES_URL=postgresql+psycopg://cc:...@localhost:5432/postgres` beside `CC_TEST_REDIS_URL`. The password starts with `fake-` (`AGENTS.md`, `.gitleaks.toml`), the database lives only as long as the job and is not reachable from outside the runner. The pytest step lists the nine files that read either variable (`grep` for `REDIS_URL_ENV`, `POSTGRES_URL_ENV`, `redis_backend`, `sink_support`), not the whole suite. `gate` is unchanged: its `needs` still names `check`, `secrets` and `dependency-review`, so a red `integration` blocks nothing.
Not verified: the workflow was checked with `actionlint` and parsed as YAML; it has not run, and neither has the Postgres or Redis cases on a real server (this sandbox cannot start either). The first run may be red for a reason in a test, not in the workflow; that is why the job stays out of the gate.
Alternative: (a) Run the whole suite in the job: simpler to keep right when a new guarded file appears, but it repeats the `check` job's work. (b) Only add the service and variables, leaving the one-file command: the Postgres variable would be unused. (c) Put Postgres in `gate`: refused by the card.
Reason: the cases that decided the generation and sink design should run somewhere; a non-required job is the cheap place.
Where: `.github/workflows/ci.yml` (job `integration`).
Revisit when: the job has run green a few times (consider making it required), or a new test file reads either variable (add it to the list; the grep above finds them).
