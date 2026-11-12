# 0335. Accessibility additions: font scaling, keyboard editing and AA contrast in every theme

Status: accepted

Context: The prototype and spec state a text scale and an edit mode driven by the mouse. The spec says text scales 85 to 150 percent and that all text meets AA.
Decision: Font scaling runs from 90 to 150 percent (the spec's 85 percent is raised to 90), with an 11px floor for captions at any scale. Edit mode is fully operable by keyboard: a focused widget moves with the arrow keys and resizes with a modifier plus arrow keys, within its min and max, and every move, resize and remove is announced to screen readers through a live region. All text meets WCAG AA in dark, light and High Contrast; the axe check (decision 0325) and token contrast tests cover it.
Alternative: Keep 85 percent (rejected: captions would fall below the 11px floor at the base size). Drag-only editing (rejected: keyboard users could not arrange the grid).
Reason: These are the gaps between the prototype and a usable app; fixing them now is cheaper than retrofitting widgets.
Consequences: Where the spec says 85 percent, this record wins. The drag code has a keyboard twin from the start. Contrast is checked for source ink colors in both themes, not only the main text.
Where: not built yet; `ui/` (display settings, edit mode, tests).
Revisit when: a user asks for a larger range, or the exact modifier for resize is tested with real users.
