# 0340. The real tokens are hand-written CSS variables, display settings are html attributes, and a drift test ties them to tokens.json

Status: accepted

Context: Task T1 replaces the placeholder tokens of 0322 with the design's (docs/design/tokens.json) and adds high contrast, glow, density and text scale. Decision 0301 forbids inline style and 0322 forbids localStorage, so a setting must reach CSS without either. The card asks for tokens.css written by hand, not generated.
Decision:
- `ui/src/styles/tokens.css` holds the values (`--cc-*`). Dark is the base (`:root`); light is `:root[data-theme="light"]` and, when nothing is forced, `@media (prefers-color-scheme: light) { :root:not([data-theme]) }`. So dark is the default when the system has no preference, and System still follows the OS. The theme API of 0322 is unchanged.
- Display settings are attributes on `<html>`, written by `ui/src/lib/display.tsx` and read by rules in tokens.css: `data-contrast="high"`, `data-density="compact"|"comfortable"`, `data-glow` (0 to 1.6, steps of 0.1, 17 rules) and `data-text-scale` (90 to 150, steps of 5, 13 rules). The values are snapped to those steps in code. Like the theme, they live in memory only (no persistence yet).
- High contrast sets opaque glass and bar, a stronger hairline, text 3 raised to text 2 (all from tokens.json) and `--cc-blur: none`. The light variants are more specific, so they win over the dark block.
- Text scale: `html { font-size: calc(16px * scale) }`, body 14px times the scale, and `--cc-text-caption: max(11px, 12px * scale)` so captions never fall under 11px. The range is 90 to 150 percent (0335 overrides the spec's 85).
- `ui/src/styles/tokens.test.ts` parses tokens.css and fails when any token in tokens.json is missing or differs (case, spacing and a leading zero are ignored), and checks the attribute rules and that index.css only reads variables that exist.
Alternative: Set `--cc-glow` and `--cc-text-scale` from script with `style.setProperty` so the range is continuous (not taken: it works under the CSP but puts the state in two places and leaves the "from attributes" rule half true). Generate tokens.css from the JSON with a script (not taken: the card says by hand, and the drift test gives the same safety). Make dark the only palette unless `data-theme="light"` (not taken: it would drop System following the OS).
Reason: Attribute-selected rules need no script before paint and no inline style, are visible in the DOM for tests, and cost 30 short rules.
Consequences: Glow and text scale are stepped, not continuous. A value outside the steps is snapped, not rejected. The light palette is written twice in tokens.css (forced, and media); the drift test checks both copies. A new token must be added to tokens.css by hand and tokens.json is the source.
Where: `ui/src/styles/tokens.css`, `ui/src/styles/index.css`, `ui/src/lib/display.tsx`, `ui/src/styles/tokens.test.ts`.
Revisit when: settings are persisted (a /v1 preference), or a user needs finer steps.
