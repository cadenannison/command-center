# 0316. The ui/ config files are written without dependencies, so the ui gates fail until the human installs and locks

Status: accepted

Context: Task P1a creates `ui/package.json` with no dependencies and the config files only (tsconfig, Vite, Vitest, ESLint, index.html). `scripts/ui.sh` is built to skip while `ui/package.json` is absent; once it exists, `guard` requires `ui/pnpm-lock.yaml` and a `mise.toml` pnpm pin, and `fast` then runs `pnpm run typecheck` and `pnpm run lint`, which need typescript and eslint. Agents may not install packages, create the lockfile or write `ui/pnpm-workspace.yaml`.
Decision: Write the files as the finished config, with real scripts (`tsc --noEmit`, `eslint .`, `vitest run`, `vite build`), and do not add stub scripts or fake dependencies to make `ui:fast` pass. Until the human applies `p1a-guard.patch`, creates the lockfile and installs the approved dev dependencies, `mise run check:fast` fails in its `ui:fast` step. Choices inside the files:
- `vite.config.ts`: host 127.0.0.1, `allowedHosts` `["localhost", "127.0.0.1"]`, `cors: false`, `strictPort` on 5173, and `/v1` proxied to `http://127.0.0.1:8765` (the app's default port), no `changeOrigin`. No Tailwind plugin yet (the Tailwind task adds it with its source).
- `tsconfig.json`: strict plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` and `verbatimModuleSyntax`; `types` is `["vite/client"]`; it includes `src` and the config files.
- `vitest.config.ts`: `passWithNoTests` off, so an empty suite fails, which backs `ui/.test-floor` (0303); `environment: "jsdom"`; test files are `src/**/*.test.{ts,tsx}`.
- `eslint.config.js`: flat config, `strictTypeChecked`, react-hooks rules, and rules that ban `eval`, `new Function`, `dangerouslySetInnerHTML` and `localStorage` (0301 item 7, AGENTS.md rule 7). `src/api/generated` is ignored (never hand-edited, 0300). Every imported package is on `docs/approved-dependencies.md`.
- `index.html` has no inline script or style and loads `/src/main.tsx`, which P1b writes.
Alternative: Stub scripts that print "ok" (rejected: AGENTS.md forbids faking a check). Put placeholder devDependencies in `package.json` (rejected: the card says none, and a dependency without a lockfile entry fails the install). Leave the scripts out (rejected: `ui.sh` calls them by name).
Reason: A gate that fails honestly until the toolchain exists is correct; one that passes without it is not.
Consequences: `mise run check:fast` and `mise run check` fail on the `ui:` guard until the human steps are done (apply the patch, create `ui/pnpm-lock.yaml`, install the approved dev dependencies with the frozen flags once they are in the lockfile). With the patch applied in a scratch copy and an empty lockfile the guard passes and `ui:fast` then stops at `tsc: command not found`, as expected. The Python gates and test count are unaffected.
Where: `ui/package.json`, `ui/tsconfig.json`, `ui/vite.config.ts`, `ui/vitest.config.ts`, `ui/eslint.config.js`, `ui/index.html`.
Revisit when: The dependencies are installed (P1b), or the proxy target or port changes.
