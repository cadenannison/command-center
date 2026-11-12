# 0363. The /dashboard route creates Main from the default layout and trusts the sanitizer on read

Status: accepted

Context: Task R3 adds the first screen over the dashboards routes. /today stays as it is.
Decision: `/dashboard` loads `GET /v1/dashboards` through the typed client and TanStack Query. An empty list creates "Main" from `DEFAULT_LAYOUTS.main` once (a ref guards a double create); a failure shows an alert with Retry. Tabs switch only (no create, rename or delete). A stored layout goes through `sanitizeLayout`; one that cannot be read shows the default layout with an alert and replaces the stored one only when the user changes it. Each widget body is a placeholder showing its tier ("W2 · H3 · 5×10"); the glow uses the widget's first source (blending several sources is left for the widgets). The wire layout is built field by field (`layoutToWire`) so nothing outside the model is sent. The wire allows only boolean and number options, so a string option is not sent (none exists yet; the model and the wire need aligning before one does).
Alternative: Create Main on the server at first read (rejected: a GET must not write).
Reason: The server stores what passes and the UI sanitizer stays authoritative (0355).
Consequences: The nav gains a Dashboard link; the existing /today route and tests are untouched. Widget states (loading, empty, error, stale, not connected) exist as shell props and are not yet driven by data.
Where: `ui/src/features/dashboard/dashboard-page.tsx`, `use-dashboards.ts`, `wire.ts`, `widget-shell.tsx`.
Revisit when: real widgets arrive, or dashboards can be created from templates.
