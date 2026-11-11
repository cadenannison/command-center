# Approved UI dependencies

Human-edited only. Agents never edit this file (CODEOWNERS and the `.claude/settings.json` deny list
enforce it) because `bash scripts/ui.sh guard` trusts it. The policy and the reasons are decision 0301.

How to add a name: the project manager approves it, after checking the npm registry (age, weekly
downloads, repository, maintainers), and adds one line below in the form
``- `name` - why it is needed``. The guard reads only lines that start with a dash and a backticked
name, so prose anywhere else in this file (including a backticked name in it) approves nothing. A
line of the form `` `@scope/*` `` approves every package in that scope. A package whose install-time build
step is allowed (`onlyBuiltDependencies` or `allowBuilds`) also needs a note on its line saying why.
A name approved here may still be refused by the guard for another reason: an exact version is required.

Versions are not listed here; the lockfile pins them.

## Runtime
- `react`
- `react-dom`
- `@tanstack/react-query`
- `@tanstack/react-router`
- `radix-ui` - the primitives shadcn components use
- `class-variance-authority`
- `clsx`
- `tailwind-merge`
- `lucide-react`

## Build and test
- `vite`
- `@vitejs/plugin-react`
- `typescript`
- `@types/react`
- `@types/react-dom`
- `@types/node`
- `tailwindcss`
- `@tailwindcss/vite`
- `vitest`
- `@testing-library/react`
- `@testing-library/user-event`
- `@testing-library/jest-dom`
- `jsdom`
- `@playwright/test`
- `@axe-core/playwright`
- `eslint`
- `@eslint/js`
- `typescript-eslint`
- `eslint-plugin-react-hooks`
- `globals`
- `prettier`
- `openapi-typescript` - dev only, generates the TypeScript types from docs/generated/openapi.json
- `openapi-fetch` - small typed fetch wrapper that consumes those types

An OpenAPI client generator is not approved: the scaffold task proposes one by name, with registry
facts, for approval.
