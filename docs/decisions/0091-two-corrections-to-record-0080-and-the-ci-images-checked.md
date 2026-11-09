# 0091. A correction to record 0080 on the card's instruction, and the CI images checked

Status: accepted

Context: Task 4d. The card asked to fix 0080's title/Where mismatch (the title said four test files; Where listed three, because the fourth, `test_normalizer_atomic.py`, needed no change) and to check that the CI integration job's Postgres image matches `docker-compose.yml`.
Decisions:
1. **0080 was edited in place**, on its title line and its Where line: "Three existing test files ..." and a sentence naming the fourth file as checked and unchanged. AGENTS.md lets an old record change only on its Status and Sources lines, and says to supersede instead. This is a deviation: the card named this correction explicitly, and a superseding record for a typo-level fix would leave the wrong title in the index. The file name (`...-in-four-test-files.md`) was not changed. The edit is two lines and is visible in the diff; to refuse it, restore those two lines and the index regenerates. 0072 was not treated the same way: its correction is new information, so it went in a new record (0090) and a Status pointer.
2. **The Postgres image already matched**: `docker-compose.yml` and `.github/workflows/ci.yml` both use `postgres:17-alpine`. CI was not changed. The Redis images differ in precision only: compose `redis:7-alpine`, CI `redis:7.4-alpine`; both are Redis 7, and the card did not ask for it, so it was left.
3. **Three assertions in `tests/test_settings_disconnect_order.py` were updated**, after the project manager added that file to the allowance in `.claude/allow-test-edits`. Only the expected values changed, each with a one-line comment: the journal of a disconnect is `bump, delete_secrets, bump, delete_events` (was without the second bump), the generation after a failed purge is 2 (was 1; the purge bumps before its delete fails), and after the retry 4 (was 2; two disconnects, each ending two higher than it started). This is the effect of 0086, which listed these as "Not done"; no assertion was loosened.
Alternative: (a) A superseding record for 0080: see item 1. (b) Change the CI Postgres image anyway to pin more tightly: no mismatch to fix.
Reason: keep the correction small and say plainly that it breaks the Status-only rule.
Where: `docs/decisions/0080-...md`; `docker-compose.yml` and `.github/workflows/ci.yml` read, not changed.
Revisit when: the images are pinned to a patch version or by digest (then compose and CI should change together).
