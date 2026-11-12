# 0341. Sora is self-hosted from ui/public/fonts with font-display swap, and tabular figures come from a class

Status: accepted

Context: The design uses Sora for headings, times, pills and badges, with tabular figures. The card forbids an npm font package. The strict CSP of 0301 allows same-origin fonts.
Decision: `docs/design/assets/sora.woff2` is copied to `ui/public/fonts/sora.woff2` and loaded by an `@font-face` in `ui/src/styles/index.css` (`/fonts/sora.woff2`, weights 100 to 800, `font-display: swap`). The `.tnum` class sets `font-feature-settings: "tnum"`; Pill and Badge carry it, and so do times in the gallery. Body text stays in the system font.
Alternative: An npm font package such as fontsource (rejected by the card, and a new dependency). Preloading the font from index.html (not taken yet; a flash of the system font is acceptable for a local app).
Reason: One file, served by the same origin that serves the app, no third party.
Consequences: The Sora license file `OFL-Sora.txt` was named in the card but is not in `docs/design/assets/`, and the sandbox could not download it, so it is NOT in `ui/public/fonts/`. The OFL requires the license text to travel with the font, so the human must add it before this is committed. Whether Sora's tnum feature gives "1111" and "0000" equal widths is checked by `ui/e2e-gallery/gallery.spec.ts`, which was not run.
Where: `ui/public/fonts/`, `ui/src/styles/index.css`.
Revisit when: the font file changes, or first paint shows a distracting swap.
