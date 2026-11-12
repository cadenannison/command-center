# Design reference

These files are a reference, not shipped code. Nothing in ui/ imports or serves them (decision 0330).

| File | What it is |
|---|---|
| `spec.md` | The written design: tokens, layout, widget anatomy, size rules, states, motion, Chat, History, Settings, and what is still to come. |
| `prototype.html` | A clickable prototype. Open it in a browser. Fonts and the logo are in `assets/`. |
| `tokens.json` | The prototype's CSS variables (dark, light, high contrast), priority colors and shape, glow, density, type and motion values, as data. |

Order of authority when they disagree: `spec.md`, then `prototype.html`, then `tokens.json`. Decisions
0331 to 0336 override the spec where they say so (for example the 90 percent font-scale floor in 0335).

The prototype's Design rules page never ships. The prototype uses inline script and style, which the
strict CSP (decision 0301) forbids in ui/, so its code is not a starting point for the UI.

Decision 0346: `tokens.json` (and `ui/`) carry four AA-adjusted values (dark text 3 #9AA9BD, light text 3 #4A596D, light overdue #A21E34, light ice #08589A); `prototype.html` and `spec.md` keep the originals.
