# 0361. Editing: 12 columns only, pointer capture, a keyboard twin, resize from the right, bottom and corner

Status: accepted

Context: Task R3 adds move and resize. Decision 0335 requires a keyboard twin for drag and announcements; decision 0350 says edit only at 12 columns.
Decision: Edit mode applies only at 12 columns; below that the Edit button is disabled and a status line explains why. Pointer: the header moves a widget and three handles (right edge, bottom edge, bottom-right corner) resize it, with pointer capture and no library. The dragged box follows the pointer; a dashed outline shows the snapped cell, and the other widgets show the result of `move` or `resize` (so they slide). Release commits, Escape or a cancelled pointer reverts. Keyboard: in edit mode a header is `role="button"` with tabindex 0; Enter picks up, arrows move, Shift and arrows resize (a size grows to the right and down), Enter drops, Escape cancels, and leaving the header with Tab drops it where it is. A polite live region announces pick-up, every step ("Events moved to column 7, row 1."), a step that changed nothing, drop and cancel. Pinned widgets neither move nor show handles; no UI pins yet.
Alternative: Resize handles on all four edges (rejected for now: the layout model keeps x and y as the origin, so left and top handles need a combined move and resize; the keyboard and the right, bottom and corner handles cover every size). Cancel on blur (rejected: Tab would silently lose the change).
Reason: One edit path (the model's `move` and `resize`) serves pointer and keyboard, so they cannot disagree.
Consequences: In edit mode the header is a button, so its `h2` heading is not exposed as a heading to a screen reader; the label carries the title. Touch dragging relies on `touch-action: none` on headers and handles; not shown on a device.
Where: `ui/src/features/dashboard/dashboard-grid.tsx`, `editing.ts`.
Revisit when: pinning or left and top resize handles are added.
