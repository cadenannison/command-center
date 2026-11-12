# 0343. Token details the card left open: source ids, glow scaling, scrim and the on-ice colors

Status: accepted

Context: Spec.md and tokens.json disagree or are silent in a few places the base components need.
Decision:
- Source ids are the six in tokens.json (`cal`, `canvas`, `ls`, `gmail`, `wx`, `manual`; `ui/src/lib/sources.ts`). The spec's eight user-assignable colors (violet to pink) need values tokens.json does not have, so they wait for the settings task. A `data-source` attribute selects `--cc-src` (glow rgb) and `--cc-ink` (label ink) in index.css.
- Glow: the spec says the ring and both shadows are multiplied by the glow setting; the prototype multiplies only the shadows. The spec wins (0330): at glow 0 there is no ring either.
- Tokens not in tokens.json, added by hand and not covered by the drift test: `--cc-on-ice` and `--cc-on-over` (text on an ice or overdue fill: near-black in dark, white in light, chosen for AA), `--cc-scrim` (a faint fill behind glass text: dark 28 percent, light 30 percent, none in high contrast) and the spacing scale.
- Pill: priority is rounded and clamped to 1 to 10 and the clamped number is printed; NaN renders nothing rather than a wrong number. Fill and ink come from tokens (`bg-(--cc-p)`, `text-(color:--cc-pill-text)`), so no raw color is in a component.
- The Tailwind names of 0322 stay (`bg-bg`, `text-fg`, `bg-accent`, `bg-danger`) and point at the new tokens; `surface` and `border` are replaced by `glass` and `line`, and rounded-sm/md/lg by `rounded-chip`, `-control`, `-widget`, `-pill`, `-block`. Badge gains `accent` and its default is now the chip look.
Alternative: Invent eight source colors now (rejected: design values are not mine to make). Follow the prototype for the ring (rejected: spec.md ranks first).
Reason: Smallest set of choices that makes the components complete and keeps every raw value in tokens.css.
Consequences: The contrast of text on ice, over and glass in all three modes is unmeasured until the axe run. `--cc-on-*` and `--cc-scrim` may need design review.
Where: `ui/src/styles/`, `ui/src/lib/sources.ts`, `ui/src/components/ui/`.
Revisit when: the design pass supplies the eight source colors or the on-ice values, or axe reports a contrast failure.
