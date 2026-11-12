# 0346. Four token values are adjusted to reach AA on bare orb hot spots

Status: accepted

Context: The contrast test of 0345 found four values from docs/design/tokens.json that fall under 4.5:1 when text sits directly on the backdrop at an orb's brightest point (not on glass). The project manager approved the proposed values.
Decision: Changed in `ui/src/styles/tokens.css` and `docs/design/tokens.json` (nothing else):
- dark text 3: #8E9DB2 to #9AA9BD (was 4.08 and 4.47, now 4.70 at the lowest)
- light text 3: #566579 to #4A596D (was 3.79, now 4.56)
- light overdue (also light high contrast, which inherits it): #B4233C to #A21E34 (was 4.13, now 4.83)
- light ice (also light high contrast): #0A64B0 to #08589A (was 3.87, now 4.66)
High-contrast text 3 values, source inks, on-ice and on-over are unchanged. `FROM_TOKENS_JSON` in `contrast.test.ts` is now empty; the test still fails on any failing pair and on a listed pair that starts passing.
Alternative: Leave the values and list the failures (rejected: AA is a requirement of 0335 in every theme). Change the backdrop orbs instead (not taken: they are the design's look).
Reason: Smallest shifts that clear 4.5:1 with a margin, keeping the hue.
Consequences: `docs/design/prototype.html` and `spec.md` keep the original values; per 0330 they rank above tokens.json, so the design reference now disagrees with tokens.json on these four (a note in `docs/design/README.md` says so). The on-ice and on-over foregrounds still pass on the new fills (checked by the test). Light ice is a little darker everywhere it is used.
Where: `ui/src/styles/tokens.css`, `docs/design/tokens.json`, `ui/src/styles/contrast.test.ts`.
Revisit when: the design owner updates the prototype and spec to these values (then drop the README note).
