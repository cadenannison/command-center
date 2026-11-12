# 0342. The gallery route is dev only and its Playwright spec runs against the dev server

Status: accepted

Context: The card wants a /gallery route that shows tokens, components and every display setting, excluded from the production build. The existing Playwright config serves the production build with `vite preview`, where the gallery must not exist.
Decision: `ui/src/router.tsx` creates the lazy gallery component only when `import.meta.env.DEV` is true; Vite folds that to false in a build, so the dynamic import and `ui/src/features/gallery/` are left out of the bundle (checked: the built JS has none of the gallery's text). The `/gallery` route stays in the route tree so route types do not change; in a build it redirects to /today. The new spec is `ui/e2e-gallery/gallery.spec.ts` with its own `ui/playwright.gallery.config.ts`, which starts the dev server on 127.0.0.1:5174. It is not part of `mise run ui:e2e`, and the existing config and spec are untouched.
Alternative: Put the spec in `ui/e2e/` (rejected: the existing config tests the build, where /gallery redirects). Add a second web server to the existing config (rejected: it edits a committed file the card did not name). Always ship the gallery (rejected by the card).
Reason: The only way to test a dev-only page is against the dev server.
Consequences: The gallery spec is not run by `ui:e2e` or CI until someone wires it in; the human runs it by hand. `tsconfig.json` now includes `e2e-gallery` and the new config.
Where: `ui/src/router.tsx`, `ui/src/features/gallery/`, `ui/e2e-gallery/`, `ui/playwright.gallery.config.ts`.
Revisit when: CI should run the gallery spec, or the gallery is replaced by a component catalog.
