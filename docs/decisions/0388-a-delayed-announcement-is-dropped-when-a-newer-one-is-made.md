# 0388. A delayed live-region announcement is dropped when a newer one is made

Status: accepted

Context: After a dialog closes, `announceLater` in `dashboard-view.tsx` waits 100 ms so the live region is visible again, then announces ("Added Weather ...", the applied template). In the test "undoes and redoes an add" the Undo or Redo click could come before that timer fired; under CPU load the timer fired after "Undone." and replaced it with "Added Weather ...". 10 of 24 runs failed with 8 files in parallel; 20 of 20 runs passed alone. This is a real defect, not only a test one: a screen reader user who presses Undo right after Add hears the old message last.
Decision: One pending timer is kept in a ref. `announce` cancels it, `announceLater` replaces it, and unmount cancels it. So a delayed announcement is dropped if anything is announced after it was queued. The existing test is unchanged; `dashboard-announce.test.tsx` waits past the delay on purpose, and fails without the change.
Alternative: Fake timers in the existing test (rejected: it would hide the defect, and Radix needs real timers). Raise the waitFor timeout or add a retry (rejected: the text is replaced for good, so waiting longer does not help). Let the later message queue behind the earlier one (rejected: the earlier one is stale by then).
Reason: The last action's message is the true one; a stale one must never win.
Where: `ui/src/features/dashboard/dashboard-view.tsx` (`announce`, `announceLater`), `dashboard-announce.test.tsx`.
Revisit when: announcements get a queue or a polite and an assertive region of their own.
