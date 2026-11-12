# 0360. Dashboard grid geometry: absolute rectangles, columns from the window, zoom on rows and gap

Status: accepted

Context: Task R3 draws the layout model (0331, 0350) as a grid. Neighbours must slide over 240ms (spec, Motion) and the UI has a strict CSP with no inline style (0301).
Decision: Each widget is an absolutely positioned box whose left, top, width and height come from its cells (`features/dashboard/metrics.ts`). The column count is 12, 8 or 4 from `window.innerWidth` (`columnsForWidth`); the pixel width of a column is the grid container's measured width, both kept current by one ResizeObserver. Zoom (70 to 130 percent, a slider; not stored, because localStorage is banned) scales the 40px row unit and the 14px gap; the columns always fill the container. The numbers reach the DOM through React's `style` prop, which sets CSSOM properties; the markup carries no `style` attribute.
Alternative: CSS grid with `grid-column` and `grid-row` (rejected: a grid placement cannot be transitioned, so neighbours would jump). Scaling with `transform: scale` (rejected: it blurs text and breaks pointer maths).
Reason: Absolute boxes animate with a plain transition and make the pointer-to-cell maths a division. CSSOM writes are allowed by `style-src 'self'`; only a parsed `style` attribute is blocked.
Consequences: Not shown in a real browser by the agent: that Chrome accepts these CSSOM writes under the production CSP header (the CSP header is still an api task). If it does not, the fallback is CSS custom properties set per item and a stylesheet using them. At 8 and 4 columns the layout is shown through `fitToColumns` and is read-only (0361). The shell widens for /dashboard only.
Where: `ui/src/features/dashboard/metrics.ts`, `use-container-width.ts`, `dashboard-grid.tsx`; `ui/src/router.tsx` (wide shell).
Revisit when: the CSP header ships, or zoom needs to persist (a display setting in /v1).
