# 0362. Layout saving: debounced, one at a time, and a 409 reloads the latest version and says so

Status: accepted

Context: Task R3 saves with `If-Match` revisions (0355-0357). Two tabs must not overwrite each other, and a failure must never be silent.
Decision: `LayoutSaver` waits 800ms after the last change, sends the latest layout only, keeps one request in flight and sends a change made meanwhile afterwards with the new revision. Leaving edit mode and switching tabs send at once (a switch first waits for a save in flight and then sends what is queued); leaving the page sends a waiting change on unmount. A 409 stops the saver: the page refetches the list, remounts the dashboard on the server's version and shows "This dashboard was changed somewhere else. Showing the latest version; your last change was not saved." If the refetch fails the alert offers Reload. Any other failure keeps the change, shows an alert with the fixed ApiError text and a Retry button. A tab switch is refused while a save has failed. History (undo and redo) lives in the view and starts over after a reload.
Alternative: Merge the other writer's change with ours (rejected: layouts are small and a silent merge hides a surprise). Retry a failed save automatically (rejected: the card forbids silent retries; the user sees the error and chooses).
Reason: The last-writer-loses rule is the one the server enforces; the UI makes the loss visible instead of hiding it.
Consequences: Closing the browser tab inside the 800ms window loses that change (no `beforeunload` handler). A save that fails after the user left the page cannot be shown. Not shown in a browser by the agent.
Where: `ui/src/features/dashboard/layout-saver.ts`, `dashboard-view.tsx`, `dashboard-page.tsx`, `dashboards-api.ts`.
Revisit when: dashboards sync live between devices, or a lost change is reported.
