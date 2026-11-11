# 0324. TypeScript 7.0.2 breaks eslint and the client generator, so the pin must move before lint and gen can run

Status: accepted

Context: P1b step 1 asks to verify the toolchain. With `typescript@7.0.2` (locked in `ui/pnpm-lock.yaml`): `tsc` works; `eslint .` exits with "typescript-eslint does not support TS 7.0" (typescript-eslint 8.72.1 peer range is `>=4.8.4 <6.1.0`); `openapi-typescript` 7.13.0 (peer `^5.x`, the newest published) crashes with `Cannot read properties of undefined (reading 'createKeywordTypeNode')` because TypeScript 7 ships no JavaScript compiler API. So `ui:fast` (lint) and `ui:gen` cannot pass, and the generated client cannot be made.
Decision: Not changed by this task. Moving `typescript` means a new lockfile resolution, which only the human may make, and `package.json` and the lockfile must stay in step. Recommended fix for the human: set `typescript` to `5.9.3` (satisfies both peer ranges; 6.0.3 satisfies typescript-eslint but not openapi-typescript's `^5.x`), re-lock, then run `mise run ui:gen` and keep `ui/src/api/generated/schema.d.ts` in the commit. Revisit TS 7 when typescript-eslint supports it (issue 10940) and openapi-typescript has a release that does not need the compiler API.
Attempted and refused: running openapi-typescript and eslint against a checksum-verified TypeScript 5.9.3 tarball downloaded into the scratchpad was blocked by the permission classifier (code from outside the lockfile). It was not retried another way, and the download was deleted.
Alternative: Edit `package.json` to `5.9.3` without the lockfile (rejected: a frozen install fails and the two disagree). Hand-write `schema.d.ts` (rejected: 0320). Replace the generator (rejected: not approved; a new name needs registry facts and approval).
Reason: A gate that fails with the true cause is correct (0316); the fix is a human-only step.
Consequences: Until the fix: `typecheck` fails on the missing generated module only; `lint` and `ui:gen` fail as above; `vitest` (33 tests) and `vite build` pass. `ui/.test-floor` does not exist yet (human-owned); the count to set is printed by `mise run ui:test:count`.
Where: `ui/package.json` (`typescript`), `ui/pnpm-lock.yaml` (human).
Revisit when: The human re-locks, or typescript-eslint and openapi-typescript support TypeScript 7.
