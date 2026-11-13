# 0375. A background refetch failure shows a notice, not the error panel

Status: accepted

Context: `DashboardPage` returned the full error panel whenever the dashboards query was in error, even when it still held data. One dropped refetch (window focus, retry) unmounted `DashboardView` and any unsaved layout edit with it; the saver's dispose send is fire-and-forget, so a failure could no longer be shown (audit R10, Q07). Verified against the current code: `dashboard-page.tsx` had the check before `current` was used.
Decision: The full panel (with Retry) shows only when the query is in error and has no data. With data, the page keeps the tabs and the view mounted and shows a `role="alert"` notice, "Couldn't refresh. Showing your last saved view.", with a Retry button (disabled while fetching). The text is fixed; no server text is shown. The notice follows the query: it disappears on the next successful fetch. A successful refetch while the user has unsaved edits changes nothing on screen: the view's history is initialised once and keyed by dashboard id and conflict epoch, so a new `dashboard` prop does not reset it. Divergence is settled by the existing If-Match path: the next save sends the revision it was based on, a 409 triggers the existing refetch-and-notice flow.
Alternative: Keep the panel and rely on the dispose send (rejected: the edit view is lost and a failure is invisible). A dismiss button (rejected: the notice is true until a fetch succeeds; Retry is the action). Merging server layout into local edits (rejected: the revision check already decides this).
Reason: A flaky request must not cost the user their view or their work.
Consequences: Tests in `dashboard-page.refetch.test.tsx` cover refetch failure with pending edits, success while dirty, Retry, a tab switch during a save (waits, one PUT), a failed save on switch, and unmount with a pending edit (one PUT). The save status still has no `role="status"` (Q07's R20b part is not in this card).
Where: `ui/src/features/dashboard/dashboard-page.tsx`.
Revisit when: the saver gets a durable queue, or the page moves to a router loader.
