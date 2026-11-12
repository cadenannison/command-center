# 0331. Widgets merge one kind per widget, size by grid cells, and the layout is a snap grid in version 1

Status: accepted

Context: The spec defines many widgets on a 12-column grid. Rules for merging sources, responding to size and storing layout must be fixed before widgets are built.
Decision:
- One kind per merge: tasks merge with tasks, events with events. Owed replies count as tasks when their toggle is on. Needs me is the only cross-kind widget. Weather, Summary and This week are their own kinds.
- Width and height tiers are independent, so one rule set per widget gives nine combinations. Tiers come from grid cells, not pixels. Tasks, Events, Canvas, LearningSuite, Owed replies, My tasks and Needs me: min 3x5, max 12x16, W 1-3 / 4-6 / 7+ columns, H 1-5 / 6-9 / 10+ rows. This week: min 3x4, max 12x10, W the same, H 1-4 / 5-7 / 8+. Weather: min 2x3, max 6x9, W 1-2 / 3-4 / 5+, H 1-4 / 5-6 / 7+. Presets S 3x5, M 4x8, L 7x10, clamped to the widget's min and max.
- What each tier shows is the table in spec.md under Size rules. Open question in the spec, settled here: at W3 + H1 the notes preview shows only when a row is expanded, so rows keep one height and 3 rows fit.
- The widget registry declares each widget's min, max and tier thresholds; widgets do not hard-code sizes.
- The layout JSON stores x, y, w, h and pinned for each widget. Version 1 is a snap grid with drag, resize and push-down compaction (widgets below move down to make room). Pinning and free placement come later (docs/backlog.md); `pinned` is stored from the start so adding them needs no migration.
Alternative: Free placement with pinning in version 1 (rejected: much more layout logic before any widget exists). Pixel breakpoints (rejected: they break when the grid zoom changes). Cross-kind merging beyond Needs me (rejected: mixed rows have no common anatomy).
Reason: Cells make tiers independent of zoom and window size; one registry gives edit mode, presets and rendering the same limits; storing the full shape now avoids a layout-format change.
Consequences: The layout format is persisted, so its keys are permanent once shipped (AGENTS.md). Widget tasks write a failing test for each tier boundary.
Where: not built yet; will live in ui/ (widget registry, layout store) and in the settings or layout /v1 endpoint added by an api task.
Revisit when: free placement and pinning are built, or a widget needs a size outside its declared range.
