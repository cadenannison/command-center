# 0005. LearningSuite (BYU) via iCal feeds

Status: accepted

Context: LearningSuite has no public API, sits behind MFA, and its terms of use do not allow scraping.
Decision: The user pastes the per-course iCal feed URLs; we read them with the generic iCal adapter. No scraping, no stored credentials.
Consequences: Coverage is limited to what the feeds expose. A feed URL is a secret (it grants read access), so it is stored in the keychain and never logged.
