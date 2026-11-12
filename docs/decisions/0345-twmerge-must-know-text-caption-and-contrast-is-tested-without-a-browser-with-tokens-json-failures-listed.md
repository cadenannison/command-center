# 0345. tailwind-merge must know text-caption, and contrast is tested without a browser with tokens.json failures listed

Status: accepted

Context: The pressed theme Button showed #0e1622 on #0a64b0 in light (2.99:1). The class list had `bg-accent text-accent-fg`, but `cn()` (tailwind-merge) read our own `text-caption` font size as a text color and dropped the earlier `text-accent-fg`; the body color then showed through. The same loss could hit any filled Badge or Button with `text-caption`. Separately, nothing measured contrast without a browser.
Decision:
- `ui/src/lib/utils.ts` extends tailwind-merge so `text-caption` is a font size. The filled values (`--cc-on-ice` on ice, `--cc-on-over` on overdue) were already right in every mode; only the merge was wrong. A new test (`button.test.tsx`) fails if a small Button or filled Badge loses its on-fill color.
- `ui/src/styles/contrast.test.ts` parses tokens.css with the browser's cascade (dark, light, and high contrast over each) and computes WCAG ratios for the pairs used together: text, text 2, text 3, overdue and ice on the backdrop, glass, scrim-over-glass, chip and bar, over the base color and each orb at its own alpha; on-ice on ice; on-over on overdue; pill ink on all ten priorities; each source ink on its tint; the ice focus ring (3:1). 4.5:1 for text. It prints a table on failure.
- Audit result: the `--cc-on-*` and `--cc-scrim` values needed no change; every pair on glass, scrim, chip and bar passes in all four modes.
- Failures that come from tokens.json values are not edited. They are text placed straight on a bare orb hot spot (not on glass) and are listed in `FROM_TOKENS_JSON` in the test with a proposed value: dark text 3 #8E9DB2 (4.08 on orb 1, 4.47 on orb 2) to #9AA9BD; light text 3 #566579 (3.79, 3.91) to #4A596D; light overdue #B4233C (4.13, 4.26) to #A21E34; light ice #0A64B0 (3.87, 3.99) to #08589A; the last two also fail in high contrast light. The test fails on any other failure and on a listed pair that starts passing.
Alternative: Delete `text-caption` and use an arbitrary size (rejected: loses the 11px floor token). Fail the test on the orb pairs (rejected: the card forbids editing tokens.json, and a red test blocks the floor). Skip orbs (rejected: they are the worst real backgrounds).
Reason: The bug was in a helper, not a token; naming the unfixable pairs keeps them visible.
Consequences: Alpha compositing is approximate (one layer at a time, orb centers); axe in a browser still decides. Orb hot spots are only reached by text outside widgets.
Where: `ui/src/lib/utils.ts`, `ui/src/components/ui/button.test.tsx`, `ui/src/styles/contrast.test.ts`.
Revisit when: the design owner changes the five tokens above (then empty `FROM_TOKENS_JSON`).
