# 0325. Honor prefers-reduced-motion globally to stop the axe check scanning mid-transition

Status: accepted

Context: The Playwright axe check flaked on color contrast. The reported colors (bg #939393, fg #7a7a7a) are blends of the light and dark tokens, not either theme's real values. The test switches theme right before the scan, and buttons use `transition-colors`, so axe sampled computed colors halfway through the transition.
Decision: Under `@media (prefers-reduced-motion: reduce)`, `ui/src/styles/index.css` sets animation and transition durations to 0s for all elements (and `scroll-behavior: auto`). `ui/playwright.config.ts` sets `use.reducedMotion: "reduce"`, so the test browser asks for reduced motion.
Alternative: Wait or poll for the transition to end in the test (rejected: a timing guess that still races on a slow runner, and it edits the test). Disable transitions only under test (rejected: hides a real state from the scan and ships no benefit). Change token values (rejected: the tokens were not the cause).
Reason: Honoring the setting is real accessibility behavior for users who ask for less motion, and it makes the final colors the only colors that exist, so the scan is deterministic without weakening it.
Consequences: Users with reduced motion see instant theme and hover changes. The scan now judges the real token colors; a genuine contrast failure would show up rather than be masked or blended.
Where: `ui/src/styles/index.css`, `ui/playwright.config.ts`.
Revisit when: motion is added that must still convey state under reduced motion (use a non-motion cue), or the test no longer switches theme before scanning.
