# 0322. Design tokens are CSS variables mapped into Tailwind, and the theme lives in memory and a data-theme attribute

Status: accepted; its placeholder values and Tailwind names are superseded by 0340 and 0343 (the theme API and in-memory choice still stand)

Context: P1b asks for tokens (color, spacing, radius, type), Tailwind mapped to them, and light, dark and follow-system themes, with neutral placeholder values and no design decisions. AGENTS.md rule 7 and decision 0301 forbid localStorage for credentials and inline script and style; `eslint.config.js` bans `localStorage` outright.
Decision:
- `ui/src/styles/tokens.css` holds the `--cc-*` variables (neutral greys and one blue, system fonts). `ui/src/styles/index.css` imports Tailwind v4 and maps the tokens with `@theme inline`, so utilities such as `bg-surface` read the variables. Components name tokens or utilities, never raw values; the design pass edits `tokens.css`.
- Themes: no `data-theme` attribute follows `prefers-color-scheme` (a media query in `tokens.css`); `data-theme="light"` or `"dark"` forces one. The switcher (Light, Dark, System) sets or removes the attribute on `<html>` from an effect; "System" removes it.
- The choice is kept in React state only. It is not persisted: localStorage is banned, and a cookie or a /v1 preference needs its own decision. Every load starts at System. There is no pre-paint inline script (strict CSP), so a forced theme is applied after first paint.
- No `style` attributes anywhere (a CSP without `unsafe-inline` blocks them).
- Button, Card, Badge and Skeleton are copied in shadcn style by hand with class-variance-authority, clsx and tailwind-merge (all approved). `radix-ui` is approved but not used yet.
Alternative: Persist the theme in localStorage (rejected: rule 7 and the lint ban). An inline script to set the theme before paint (rejected: CSP). Tailwind's `dark:` variant with a class (not taken: variables change once, utilities follow).
Reason: Variables keep the design pass to one file; an attribute switch needs no script before paint to be correct for the default case.
Consequences: A person who forces Dark sees the system theme on every reload until persistence is decided. The color values have not been checked for contrast beyond the axe smoke test, which has not been run (no browser installed).
Where: `ui/src/styles/`, `ui/src/lib/theme.tsx`, `ui/src/components/`.
Revisit when: The design pass lands, or a theme preference is stored through /v1.
