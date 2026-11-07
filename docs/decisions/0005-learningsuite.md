# 0005. LearningSuite (BYU) via iCal feeds

Status: accepted

Context: LearningSuite has no public API, sits behind MFA, and its terms of use do not allow scraping.
Decision: The user pastes the per-course iCal feed URLs; we read them with the generic iCal adapter. No scraping, no stored credentials.
Consequences: Coverage is limited to what the feeds expose. A feed URL is a secret (it grants read access), so it is stored in the keychain and never logged.
Sources (checked 2026-11-07): https://softwaresupport.byu.edu/learning-suite/student/schedule/assignment-updates-on-calendar supports only the feed claim. It describes "Get iCalendar Feed" on a course schedule, subscribing to the copied link by URL in Google Calendar or Apple Calendar, repeating the steps for each course, and items arriving as all-day events that change when the schedule changes. It calls them schedule items; it does not say that assignment due dates are in the feed. The page says nothing about a missing public API, MFA or a ban on scraping, so those parts of the Context are not sourced here.
